#!/bin/bash
# REL0-BACKUP-VERIFY v2: пробное восстановление encrypted backup во временную БД finpilot_rel0_probe.
# Passphrase-файл НЕ удаляется этим скриптом.
#
#   umask 077
#   bash rel0-backup-verify-v2.sh <PASSFILE> <EXPECTED_ALEMBIC> <BACKUP> <EXPECTED_SHA>
#
# Пример: …/passphrase 20261017_0010 \
#   /var/backups/finpilot/finpilot-staging-FA-R02-20261020T063211Z.tar.enc \
#   7661414aaaa7b21fadc58508b26393e91346b1183ca924c3fc2aa95b3d2c8a90

set -euo pipefail
umask 077

CHECK_DB=finpilot_rel0_probe
if [ "${CHECK_DB}" != finpilot_rel0_probe ]; then
  echo REFUSING_UNEXPECTED_DATABASE
  exit 1
fi

if [ "$#" -ne 4 ]; then
  echo NEED_PASSFILE_EXPECTED_ALEMBIC_BACKUP_AND_SHA
  exit 1
fi
PASSFILE=$1
EXPECTED_ALEMBIC=$2
BACKUP=$3
EXPECTED_SHA=$4

COMPANY=2f346a28-da63-4ab1-a9e8-611fe7e2dd7d
PG_CONTAINER=finpilot-staging-postgres-1
CONTAINER_DUMP=/tmp/finpilot-rel0-probe.dump
CONTAINER_LIST=/tmp/finpilot-rel0-probe.list
MIN_FREE_KB=5242880

if [ -z "$EXPECTED_ALEMBIC" ]; then
  echo EXPECTED_ALEMBIC_EMPTY
  exit 1
fi
if [ -z "$EXPECTED_SHA" ]; then
  echo EXPECTED_SHA_EMPTY
  exit 1
fi

case "$BACKUP" in
  *..*) echo BACKUP_PATH_REFUSED; exit 1 ;;
  /var/backups/finpilot/*.tar.enc) ;;
  *) echo BACKUP_PATH_REFUSED; exit 1 ;;
esac

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

TMP=$(mktemp -d /var/tmp/finpilot-rel0-probe-decrypt.XXXXXX)
chmod 700 "$TMP"
tmp_created=1
container_temps_created=0

psql_finpilot() {
  local db=$1
  local sql=$2
  printf '%s\n' "$sql" | docker exec -i "$PG_CONTAINER" \
    bash -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U finpilot -d "$1" -v ON_ERROR_STOP=1 -Atqf -' \
    psql "$db"
}

cleanup() {
  local code=$?
  if [ "${container_temps_created:-0}" = 1 ]; then
    docker exec "$PG_CONTAINER" rm -f -- "$CONTAINER_DUMP" "$CONTAINER_LIST" 2>/dev/null || true
  fi
  if [ "${tmp_created:-0}" = 1 ] && [ -d "$TMP" ]; then
    rm -rf -- "$TMP"
  fi
  if [ "$code" != 0 ]; then
    echo FAILED code="$code"
    echo PROBE_DB_MAY_REMAIN="$CHECK_DB"
  fi
  exit "$code"
}
trap cleanup EXIT

if [ "$CHECK_DB" = finpilot ] || [ "$CHECK_DB" = finpilot_restore ]; then
  echo REFUSING_PROTECTED_DATABASE
  exit 1
fi

avail=$(df -P / | awk 'NR==2 {print $4}')
echo avail_kb="$avail"
if [ "$avail" -lt "$MIN_FREE_KB" ]; then
  echo LOW_DISK need_kb="$MIN_FREE_KB"
  exit 1
fi

if [ ! -f "$BACKUP" ] || [ -L "$BACKUP" ]; then
  echo ARCHIVE_NOT_REGULAR
  exit 1
fi
archive_sha=$(sha256sum -- "$BACKUP" | awk '{print $1}')
if [ "$archive_sha" != "$EXPECTED_SHA" ]; then
  echo ARCHIVE_SHA_MISMATCH
  exit 1
fi
if [ -f "${BACKUP}.sha256" ]; then
  backup_dir=$(dirname -- "$BACKUP")
  backup_name=$(basename -- "$BACKUP")
  ( cd "$backup_dir" && sha256sum -c "${backup_name}.sha256" )
fi

db_exists=$(psql_finpilot postgres "SELECT count(*) FROM pg_database WHERE datname = '$CHECK_DB';")
if [ "$db_exists" != 0 ]; then
  echo ALREADY_PRESENT database="$CHECK_DB"
  exit 1
fi

openssl enc -d -aes-256-cbc -pbkdf2 -salt \
  -pass "file:$PASSFILE" -in "$BACKUP" -out "$TMP/bundle.tar"
tar -xf "$TMP/bundle.tar" -C "$TMP"
if [ -f "$TMP/database.dump" ] && [ ! -L "$TMP/database.dump" ]; then
  DUMP_SRC="$TMP/database.dump"
  echo BACKUP_FORMAT=fa_r02
  if [ ! -f "$TMP/manifest.txt" ] || [ -L "$TMP/manifest.txt" ]; then
    echo ARCHIVE_MEMBER_MISSING manifest.txt
    exit 1
  fi
elif [ -f "$TMP/db.dump" ] && [ ! -L "$TMP/db.dump" ]; then
  DUMP_SRC="$TMP/db.dump"
  echo BACKUP_FORMAT=checkpoint
  for required in db.dump files.tar files.sha256 manifest.txt; do
    if [ ! -f "$TMP/$required" ] || [ -L "$TMP/$required" ]; then
      echo ARCHIVE_MEMBER_MISSING "$required"
      exit 1
    fi
  done
else
  echo ARCHIVE_MEMBER_MISSING database.dump_or_db.dump
  exit 1
fi
echo ARCHIVE_LAYOUT_OK

manifest_schema=
if [ -f "$TMP/manifest.txt" ]; then
  manifest_schema=$(grep -E '^schema_before=' "$TMP/manifest.txt" | head -1 | cut -d= -f2- || true)
  if [ -n "$manifest_schema" ]; then
    echo manifest_schema_before="$manifest_schema"
  fi
fi

container_temps_created=1
docker cp "$DUMP_SRC" "$PG_CONTAINER:$CONTAINER_DUMP"
docker exec "$PG_CONTAINER" pg_restore -l "$CONTAINER_DUMP" \
  | awk '/^;/ { print; next } / DATABASE / { print ";" $0; next } { print }' \
  > "$TMP/restore.list"
docker cp "$TMP/restore.list" "$PG_CONTAINER:$CONTAINER_LIST"

psql_finpilot postgres "CREATE DATABASE $CHECK_DB;"
docker exec "$PG_CONTAINER" \
  bash -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -U finpilot \
    -d "$1" --no-owner --exit-on-error --single-transaction -L "$2" "$3"' \
  pg_restore "$CHECK_DB" "$CONTAINER_LIST" "$CONTAINER_DUMP"

restored_alembic=$(psql_finpilot "$CHECK_DB" "SELECT version_num FROM alembic_version;")
echo restored_alembic="$restored_alembic"

if [ -n "$manifest_schema" ] && [ "$restored_alembic" != "$manifest_schema" ]; then
  echo MANIFEST_SCHEMA_MISMATCH manifest="$manifest_schema" restored="$restored_alembic"
  exit 1
fi

if [ "$restored_alembic" != "$EXPECTED_ALEMBIC" ]; then
  echo EXPECTED_ALEMBIC_MISMATCH expected="$EXPECTED_ALEMBIC" restored="$restored_alembic"
  exit 1
fi

psql_finpilot "$CHECK_DB" "
SET row_security = off;
SELECT 'posted_cash=' || count(*)::text FROM cash_transactions
  WHERE company_id = '$COMPANY' AND status = 'posted';
SELECT 'cash_in=' || coalesce(sum(amount) FILTER (WHERE direction = 'in'), 0)::text
  FROM cash_transactions WHERE company_id = '$COMPANY' AND status = 'posted';
SELECT 'cash_out=' || coalesce(sum(amount) FILTER (WHERE direction = 'out'), 0)::text
  FROM cash_transactions WHERE company_id = '$COMPANY' AND status = 'posted';
SELECT 'opening_active_rows=' || count(*)::text FROM opening_balances
  WHERE company_id = '$COMPANY' AND status = 'active';
SELECT 'opening_active_sum=' || coalesce(
  sum(amount) FILTER (WHERE status = 'active'), 0
)::text FROM opening_balances WHERE company_id = '$COMPANY';
SELECT 'revenue_oct_ex_vat=' || coalesce(sum(amount_ex_vat), 0)::text
  FROM revenue_entries
  WHERE company_id = '$COMPANY' AND status = 'posted' AND entry_type = 'sale'
    AND recognition_date >= '2026-10-01' AND recognition_date < '2026-11-01';
" > "$TMP/baseline.out"
cat "$TMP/baseline.out"

posted_cash=$(grep '^posted_cash=' "$TMP/baseline.out" | cut -d= -f2- || true)
if [ "$posted_cash" = 0 ] || [ -z "$posted_cash" ]; then
  echo RLS_SUSPECTED posted_cash="$posted_cash"
  exit 1
fi
grep -qx 'posted_cash=5' "$TMP/baseline.out" || { echo POSTED_CASH_MISMATCH; exit 1; }

grep -qx 'cash_in=27000.00' "$TMP/baseline.out" || { echo CASH_IN_MISMATCH; exit 1; }
grep -qx 'cash_out=46500.50' "$TMP/baseline.out" || { echo CASH_OUT_MISMATCH; exit 1; }

opening_rows=$(grep '^opening_active_rows=' "$TMP/baseline.out" | cut -d= -f2- || true)
if [ "$opening_rows" = 0 ] || [ -z "$opening_rows" ]; then
  echo OPENING_MISMATCH reason=no_active_opening_rows
  exit 1
fi
grep -qx 'opening_active_sum=100000.00' "$TMP/baseline.out" || { echo OPENING_MISMATCH; exit 1; }

grep -qx 'revenue_oct_ex_vat=20002.00' "$TMP/baseline.out" || { echo REVENUE_OCT_MISMATCH; exit 1; }

echo BASELINE_OK

psql_finpilot postgres "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$CHECK_DB' AND pid <> pg_backend_pid();"
psql_finpilot postgres "DROP DATABASE $CHECK_DB;"
echo PROBE_DB_DROPPED

rm -rf -- "$TMP"
tmp_created=0
echo REL0_BACKUP_VERIFY_OK
