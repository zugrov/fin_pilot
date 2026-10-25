#!/bin/bash
# REL0-BACKUP-CREATE: encrypted checkpoint backup staging (db.dump layout).
# Не восстанавливает finpilot, не выполняет probe verify.
# Passphrase-файл НЕ удаляется этим скриптом.
#
#   umask 077
#   bash rel0-backup-create.sh <PASSFILE> <RESTART_AFTER>
#   RESTART_AFTER=yes|no  — yes: поднять api/worker/beat и ждать health; no: оставить остановленными (окно).
#
# Только после «команды ok» владельца на согласованный список CREATE.

set -euo pipefail
umask 077

if [ "$#" -ne 2 ]; then
  echo NEED_PASSFILE_AND_RESTART_AFTER
  exit 1
fi
PASSFILE=$1
RESTART_AFTER=$2

case "$RESTART_AFTER" in
  yes|no) ;;
  *) echo RESTART_AFTER_INVALID; exit 1 ;;
esac

STAMP=$(date -u +%Y%m%dT%H%M%SZ)
BASE=/var/backups/finpilot
WORK=
MIN_FREE_KB=5242880
PG=finpilot-staging-postgres-1
ENC="$BASE/finpilot-staging-REL0-${STAMP}.tar.enc"
services_stopped=0

COMPOSE=(docker compose
  --env-file /fin_pilot/.env
  -f infra/docker-compose.staging.yml
  -f /var/tmp/finpilot-release-be9e47a/compose.override.yml
  -p finpilot-staging
)
RECOVERY_CMD='cd /fin_pilot && docker compose --env-file /fin_pilot/.env -f infra/docker-compose.staging.yml -f /var/tmp/finpilot-release-be9e47a/compose.override.yml -p finpilot-staging start api worker beat'

compose() {
  ( cd /fin_pilot && "${COMPOSE[@]}" "$@" )
}

if [ -L "$PASSFILE" ] || [ ! -f "$PASSFILE" ]; then
  echo PASSPHRASE_NOT_REGULAR
  exit 1
fi
pass_bytes=$(stat -c '%s' -- "$PASSFILE" 2>/dev/null || stat -f '%z' -- "$PASSFILE")
if [ "$pass_bytes" -le 0 ]; then
  echo PASSPHRASE_EMPTY
  exit 1
fi
pass_mode=$(stat -c '%a' -- "$PASSFILE" 2>/dev/null || stat -f '%OLp' -- "$PASSFILE")
pass_dir=$(dirname -- "$PASSFILE")
dir_mode=$(stat -c '%a' -- "$pass_dir" 2>/dev/null || stat -f '%OLp' -- "$pass_dir")
case "$pass_mode" in
  600) ;;
  *) echo PASSPHRASE_PERMISSIONS; exit 1 ;;
esac
case "$dir_mode" in
  700) ;;
  *) echo PASSPHRASE_DIR_PERMISSIONS; exit 1 ;;
esac
case "$PASSFILE" in
  *..*) echo PASSFILE_PATH_REFUSED; exit 1 ;;
  /tmp/finpilot-backup-secret.*/passphrase) ;;
  *) echo PASSFILE_PATH_REFUSED; exit 1 ;;
esac

cleanup() {
  local code=$?
  docker exec "$PG" rm -f -- /tmp/rel0-db.dump 2>/dev/null || true
  rm -f -- "$ENC.partial" 2>/dev/null || true
  if [ -n "${WORK:-}" ] && [ -d "$WORK" ]; then
    rm -rf -- "$WORK"
  fi
  if [ "$code" != 0 ] && [ "$services_stopped" = 1 ]; then
    if compose start api worker beat; then
      echo SERVICES_RESTARTED_AFTER_FAILURE
    else
      echo SERVICES_MAY_BE_STOPPED
      echo RECOVERY_CMD="$RECOVERY_CMD"
    fi
  fi
  if [ "$code" != 0 ]; then
    echo FAILED code="$code"
  fi
  exit "$code"
}
trap cleanup EXIT

if ! docker inspect "$PG" >/dev/null 2>&1; then
  echo PG_CONTAINER_MISSING container="$PG"
  exit 1
fi

TAR_IMAGE=$(docker inspect --format '{{.Config.Image}}' "$PG")
if ! docker image inspect "$TAR_IMAGE" >/dev/null 2>&1; then
  echo TAR_IMAGE_MISSING image="$TAR_IMAGE"
  exit 1
fi
if ! docker run --rm --pull never "$TAR_IMAGE" tar --version >/dev/null 2>&1; then
  echo TAR_BINARY_MISSING image="$TAR_IMAGE"
  exit 1
fi

mapfile -t IMPORTS_CANDIDATES < <(docker volume ls -q | grep -E '^finpilot-staging_.*imports$' || true)
if [ "${#IMPORTS_CANDIDATES[@]}" -ne 1 ]; then
  echo IMPORTS_VOLUME_REFUSED count="${#IMPORTS_CANDIDATES[@]}"
  exit 1
fi
IMPORTS_VOL="${IMPORTS_CANDIDATES[0]}"
echo imports_volume="$IMPORTS_VOL"
echo tar_image="$TAR_IMAGE"

avail=$(df -P / | awk 'NR==2 {print $4}')
echo avail_kb="$avail"
if [ "$avail" -lt "$MIN_FREE_KB" ]; then
  echo LOW_DISK need_kb="$MIN_FREE_KB"
  exit 1
fi

WORK=$(mktemp -d /var/tmp/finpilot-rel0-backup-create.XXXXXX)
chmod 700 "$WORK"

services_stopped=1
compose stop api worker beat

docker exec "$PG" bash -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U finpilot -Fc -d finpilot -f /tmp/rel0-db.dump'
docker cp "$PG:/tmp/rel0-db.dump" "$WORK/db.dump"
docker exec "$PG" rm -f -- /tmp/rel0-db.dump

docker run --rm --pull never \
  -v "${IMPORTS_VOL}:/imports:ro" \
  -v "$WORK:/out" \
  "$TAR_IMAGE" \
  tar -cf /out/files.tar -C /imports .
( cd "$WORK" && sha256sum files.tar > files.sha256 )

SCHEMA=$(docker exec "$PG" bash -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U finpilot -d finpilot -Atc "SELECT version_num FROM alembic_version;"')
printf 'schema_before=%s\n' "$SCHEMA" > "$WORK/manifest.txt"

tar -cf "$WORK/bundle.tar" -C "$WORK" db.dump files.tar files.sha256 manifest.txt
openssl enc -aes-256-cbc -pbkdf2 -salt -pass "file:$PASSFILE" \
  -in "$WORK/bundle.tar" -out "$ENC.partial"
mv "$ENC.partial" "$ENC"
chmod 600 "$ENC"
( cd "$BASE" && sha256sum "$(basename "$ENC")" > "$(basename "$ENC").sha256" )

rm -rf -- "$WORK"
WORK=

sha256sum -- "$ENC"
echo BACKUP_ENC="$ENC"

if [ "$RESTART_AFTER" = yes ]; then
  compose start api worker beat
  services_stopped=0
  health_ok=0
  attempt=0
  while [ "$attempt" -lt 30 ]; do
    attempt=$((attempt + 1))
    if curl -sf http://127.0.0.1:8090/health/live >/dev/null \
      && curl -sf http://127.0.0.1:8090/health/ready >/dev/null; then
      health_ok=1
      break
    fi
    sleep 2
  done
  if [ "$health_ok" != 1 ]; then
    echo HEALTH_NOT_READY attempts="$attempt"
    exit 1
  fi
  echo HEALTH_OK
else
  echo SERVICES_LEFT_STOPPED restart_after=no
fi

echo REL0_BACKUP_CREATE_OK
