# Окно деплоя на стенд · PR #25 + миграции `20261110_0022` и `20261111_0023`

**Назначение:** плановое окно выката на VPS **уже слитых** изменений:

- [PR #25](https://github.com/zugrov/fin_pilot/pull/25) — rate limit за Caddy, compose override, `staging_acceptance.py` (squash → `c34328f…`).
- [PR #34](https://github.com/zugrov/fin_pilot/pull/34) — **FA-R03.3-min**: fingerprint, lineage, `reconciliation_run`, миграция **`20261110_0022`** (product squash → `0fc224d…`).
- **FA-R03.4 v1** в **main**: `source_correction_finding`, миграция **`20261111_0023`** (merge `7258e2b…`).

**Деплой:** весь **main**; после migrate ожидается **`alembic head = 20261111_0023`**.

**Команды ниже CI не выполняет.** В режиме Б их выполняет Cursor по ssh, и только после отдельного письменного разрешения на конкретный `WINDOW_SHA`. Без этого разрешения команды не запускать.

**Базовые runbook:** [runbook-staging-window.md](runbook-staging-window.md), [runbook-staging-acceptance.md](runbook-staging-acceptance.md), [runbook-staging.md](runbook-staging.md).  
**Устаревшие:** [runbook-staging-window-pr25.md](runbook-staging-window-pr25.md), [runbook-staging-window-pr25-0022.md](runbook-staging-window-pr25-0022.md) — заменены этим документом.

## Режим выполнения

Номера шагов — как в [STAGING-WINDOW-READINESS.md](roadmap/STAGING-WINDOW-READINESS.md). Выбирает владелец.

**А.** Шаги 1–9 выполняет владелец по командам этого файла. Cursor делает только шаг 0 (чтение) и разбор логов.

**Б.** Cursor выполняет шаги 1–9 по ssh после отдельного письменного разрешения. В разрешении назван конкретный `WINDOW_SHA` и приложен список команд. Любой FAIL — стоп. Шаг 10 (ручной UI) всегда выполняет владелец. Шаг 0 — только чтение, после подтверждения, что VPS запущен.

**Принятое решение 2026-11-12:** режим **Б**. Письменное разрешение на конкретный `WINDOW_SHA` и подтверждение, что VPS запущен, этим решением не даны.

---

## Версии (git)

| Объект | SHA / ссылка |
| --- | --- |
| **main на момент подготовки runbook** | `1be20626d6957cf2bd192af3e428f99bc190c056` |
| Минимум для PR #25 (rate limit) | `c34328f1873c636c4c23f5eb1e545cdc774e585f` |
| Минимум для FA-R03.3-min + migration 0022 | `0fc224d5eb39355a0911e1fb61a9024eb6307a14` |
| Минимум для FA-R03.4 v1 + migration 0023 | `7258e2bb83997066ba1b541e737771078f6e628` |
| **Выкат окна** | точный `WINDOW_SHA`: полный SHA `main` с зелёными ci и e2e |

Перед окном записать в `var/${WINDOW_ID}/notes.md` и в `var/${WINDOW_ID}/window.env` строку `WINDOW_SHA=<полный sha>`. Checkout — команда шага 2: сначала `PREV_SHA`, пустой `git status --short`, затем этот SHA. `git rev-parse HEAD` обязан совпасть с `WINDOW_SHA`. Нижняя граница вида «не старее коммита» не используется.

CI **main** на `WINDOW_SHA` — **success** (backend, frontend, playwright). Playwright — настоящий прогон тестов, не пропуск. Пока прогон не зелёный, шаг 2 не начинать.

---

## Scope окна

### PR #25

- `TRUST_PROXY`, `TRUSTED_PROXY_CIDRS=172.18.0.0/16`.
- Caddy без ручного снятия `X-Forwarded-For`.
- `scripts/staging_acceptance.py`, `infra/docker-compose.prod.deploy.override.yml`, `infra/stand-patches/xlrd_stub`.
- Redis: **не** `FLUSHDB`.

### Миграция `20261110_0022` (FA-R03.3-min)

- Таблицы: `import_source_fingerprints`, `import_row_lineage`, `reconciliation_run`.
- RLS `FORCE`, политики `app_tenant()`, worker retention (`app_expire_reconciliation_runs`).
- Hook provenance после commit импорта (код API; smoke на стенде).

### Миграция `20261111_0023` (FA-R03.4 v1)

- Таблица: `source_correction_finding` (RLS, grants app/worker).
- Скан после **commit cash**: `period_overlap`, `duplicate_suspect`, `internal_transfer`.
- Период на `import_source_fingerprints` из min/max `business_date` по batch.

**Вне этого окна:** cron retention, сторно/FX, UI коррекций, публичный API и UI прогонов сверки, деплой без бэкапа. Код записи прогона и непубличный CLI уже в main; `RECONCILIATION_RUN_PERSIST_ENABLED` остаётся **false**, пока не выполнен шаг после успешной миграции и smoke.

---

## Шаг 0 · фактический baseline стенда (только чтение)

**Перед окном** (вручную на VPS; в `var/${WINDOW_ID}/baseline.json` без секретов):

```bash
# Ревизия Alembic (один из вариантов)
docker compose … exec -T backend alembic current
# или
docker compose … exec -T postgres psql -U … -d … -c 'SELECT version_num FROM alembic_version;'

git -C "${APP_ROOT}" rev-parse HEAD
git -C "${APP_ROOT}" status --short

docker compose … exec -T postgres psql -U … -d … -c \
  "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 30;"
docker compose … exec -T postgres psql -U … -d … -c \
  "SELECT pg_database_size(current_database());"

# Долгие транзакции. FAIL и стоп, если count > 0.
# Миграция 0021 берёт блокировки при lock_timeout 5s.
docker compose … exec -T postgres psql -U … -d … -c \
  "SELECT count(*) FROM pg_stat_activity WHERE state <> 'idle' AND now() - xact_start > interval '30 seconds';"

# Свободное место: avail на ФС дампа и на ФС данных docker.
# FAIL и стоп, если любое из них меньше 2 * pg_database_size.
df -B1 --output=target,avail /var/backups /var/lib/docker
free -m
ls -ld /var/backups
```

Каталога `/var/backups/finpilot` на шаге 0 может ещё не быть: его создаёт шаг 1. Это не FAIL. Путь данных docker — `docker info -f '{{.DockerRootDir}}'`. Свободное место смотреть на файловой системе этого пути и на файловой системе `/var/backups`. Если корень docker не `/var/lib/docker`, в команду `df` подставить фактический путь.

В `baseline.json` записать `long_tx_count`, `db_bytes`, `avail_backup_bytes`, `avail_docker_bytes`, `registry_ok`, `pypi_ok`, `actor_count`. `long_tx_count` должен быть 0. `avail_backup_bytes` и `avail_docker_bytes` — каждый не меньше `2 * db_bytes`. `actor_count` должен быть 1. Иначе окно остановить до бэкапа и migrate.

Сеть с VPS, без `docker pull`, без запуска контейнеров и без записи в БД. Базовый образ сборки — `python:3.12.8-slim-bookworm`. Код ответа не 200 или обрыв — `registry_ok=0` или `pypi_ok=0`.

```bash
curl -fsS -o /dev/null -w '%{http_code}\n' \
  https://pypi.org/simple/alembic/
curl -fsS -o /dev/null -w '%{http_code}\n' \
  https://files.pythonhosted.org/packages/a6/0c/c2a72d51fe56e08a08acc85d13013558a2d793028ae7385448a6ccdfae64/xlrd-2.0.1-py2.py3-none-any.whl
docker manifest inspect python:3.12.8-slim-bookworm >/dev/null && echo registry_ok
```

`docker manifest inspect` только читает реестр и не подменяет тег `finpilot-api:0.2.0`. Если registry или PyPI недоступны, шаг 2b не выполнять.

Пользователь `--as-user` уже должен быть в БД. Печатается только count, email в notes не писать. Ожидание: `1`.

Команда ниже рассчитана на оболочку, где уже подключён `window.env`. В stdout попадает только число. Email в notes не копировать.

```bash
docker compose --env-file .env \
  -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  -f infra/docker-compose.prod.deploy.override.yml \
  exec -T -e "ACTOR_EMAIL=${ACTOR_EMAIL}" postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -v ON_ERROR_STOP=1 -v actor="$ACTOR_EMAIL" -c "SELECT count(*) FROM users WHERE normalized_email = lower(:'\''actor'\'')"'
```

Шаблон `var/${WINDOW_ID}/window.env`, режим 600, без паролей и URL. `WINDOW_SHA` — кандидат с зелёными ci и e2e, не «кончик main после docs». `PREV_SHA` дописывает шаг 2.

```bash
WINDOW_ID=<id окна>
WINDOW_SHA=30491d500b45beff43bbefcf03d630fe0de362dc
PREV_SHA=
APP_ROOT=<каталог на стенде>
PERIOD=<ГГГГ-ММ>
COMPANY_ID=<uuid организации стенда>
ACTOR_EMAIL=<email пользователя finance write>
```

В `var/${WINDOW_ID}/notes.md` сразу записать сравнение, сделанное локально, не на стенде: `frontend_proxy=не менялись`, `frontend_proxy_base=c34328f1873c636c4c23f5eb1e545cdc774e585f`. Это последний известный деплой. Фактический SHA стенда до шага 0 неизвестен. Если `git rev-parse HEAD` на стенде не равен `c34328f`, перед шагом 2b заново посмотреть `git diff --stat <HEAD стенда>..30491d5 -- frontend infra`. Пустой diff — frontend и proxy не собирать. Непустой — шаг 2b не начинать, пока сборка frontend не добавлена отдельным решением.

**Повтор 2026-11-10:** `ssh -o ConnectTimeout=10 … true` → **timeout**, без повторных попыток. Факт с VPS **не подтверждён**; сценарий **A** (`20261027_0017`) по-прежнему из STATE до `baseline.json` владельца.

Если preflight SSH не проходит или шаг 0 не дал `alembic_version`, объём БД, `long_tx_count = 0`, место ≥ 2× размера БД, `actor_count = 1` и оба флага сети — окно не начинать. При `registry_ok=0` или `pypi_ok=0` шаг 2b не выполнять.

### Два сценария migrate

| Сценарий | Baseline | В логе `alembic upgrade head` |
| --- | --- | --- |
| **A (факт стенда по STATE)** | `20261027_0017` | `0017→0018→…→0023` (6 шагов) |
| **B (уже догнали 0021)** | `20261107_0021` | только `0021→0022→0023` |

---

## Оценка времени migrate (репетиция)

Локально: `cd backend && uv run python ../scripts/rehearse_staging_migrations_0022_0023.py --baseline 20261027_0017 --profile large`

Профиль **large** (2026-11-10): **200k** `cash_transactions`, **30k** `revenue_entries`, **20k** `planned_cash_events`, БД **~110 MB**.  
DDL-шаги **не сканируют** cash; время отражает накладные расходы DDL/backfill на профилях.

| Ревизия | Тип | Backfill / риск | Время upgrade (large), с |
| --- | --- | --- | ---: |
| `20261106_0018` | DDL + seed | tax_norm_versions | 0,05 |
| `20261107_0019` | DDL + seed | tax_norm_versions | 0,04 |
| `20261107_0020` | DDL + backfill | 1 `organization_profile_versions` на company | 0,05 |
| `20261107_0021` | data | UPDATE bands, trigger off, lock_timeout 5s | 0,05 |
| `20261110_0022` | DDL | provenance | 0,07 |
| `20261111_0023` | DDL | corrections | 0,05 |
| **Сумма 0018–0023** | | | **~0,31** |

| Этап | Ориентир |
| --- | --- |
| Сценарий **B** `0021→head` | **~0,12 с** (малый объём, 2026-11-10) |
| Roundtrip `head→0021` (пустые 0022/0023) | **~0,12 с** |
| **Стенд** | Факт `upgrade` start/end в `var/${WINDOW_ID}/migrate_timing.txt` (**решение владельца 2026-11-10**) |

Откат: **0018–0021** — штатный downgrade SQL на репетиции; **0022/0023** — только при пустых таблицах, иначе restore из бэкапа.

**Базовая ревизия до окна:** зафиксировать шагом 0; **ожидание по STATE:** `20261027_0017`.

---

## Предусловия

- [ ] Владелец назначил **WINDOW_ID** (например `pr25-0022-0023-YYYYMMDD`).
- [ ] Плейсхолдеры: `SSH_ALIAS`, `APP_ROOT`, `LOCAL_PORT`, `REMOTE_PROXY_PORT`, `BASE_URL`.
- [ ] Тестовый магазин ЮKassa, `STAGING_PASSWORD`, туннель — как в базовом runbook.
- [ ] **Не** боевой магазин, **не** данные клиента / ТОПКОМ, **не** `--force` / `--admin` на проде.
- [ ] На стенде лежит `var/${WINDOW_ID}/window.env` (режим 600, без секретов). `PREV_SHA` допишет шаг 2.

---

## Порядок шагов (обязательная последовательность)

0. **Baseline, только чтение.** Ревизия, долгие транзакции, место ≥ 2× размера БД. FAIL — стоп.
1. **Бэкап** в `/var/backups/finpilot/`, размер, `pg_restore --list` внутри контейнера postgres. Без PASS migrate не начинать.
2. **Код:** `PREV_SHA` в notes, чистое дерево, checkout точного `WINDOW_SHA`.
2b. **Образ api**, только после сети шага 0. Frontend и proxy не собирать, если diff от `c34328f` пустой. Затем `alembic heads` и stop api, worker, beat.
3. **Миграция:** один `alembic upgrade head` из этого образа. Сразу после — gate `alembic_version = 20261111_0023`, иначе стоп.
4. **Запуск** api, worker, beat, frontend, proxy без повторной сборки. Дамп шага 1 лежит вне `${APP_ROOT}`, checkout его не затирает.
5. **Smoke post-migrate:** health, revision **0023**, таблицы/RLS, worker grants, import → fingerprint/lineage + **коррекции** (§ ниже).
6. **Флаг** `RECONCILIATION_RUN_PERSIST_ENABLED=true` в `.env` стенда и перезапуск api — только если шаг 5 **PASS**.
7. **Образцы:** одна схема ниже. На стенд только `var/${WINDOW_ID}/synthetic/`.
8. **CLI:** пробный запуск, затем `--yes`, одна новая строка.
9. **Флаг обратно в false** и перезапуск api. `true` оставить только отдельным явным решением владельца.
10. **Приёмка PR #25 и ручной UI** — UI всегда владелец.
11. **Завершение:** дамп после окна, отчёт `var/${WINDOW_ID}/` (`baseline.json`, `migrate_timing.txt`, smoke batch id), остановка VPS по политике.

Файлы compose. `prod` — `infra/docker-compose.prod.yml`, `ip` — `infra/docker-compose.prod.ip.override.yml`, `deploy` — `infra/docker-compose.prod.deploy.override.yml` (заглушка xlrd и `UV_NO_SYNC=1` у api, worker, beat).

| Шаг | Команда | Файлы | deploy override |
| --- | --- | --- | --- |
| 2b stop | `stop api worker beat` | prod, ip, deploy | да, чтобы остановить тот же проект |
| 3 | `run` одноразового migrate | prod, ip, deploy | да; alembic xlrd не читает |
| 4 | `up -d` постоянных сервисов | prod, ip, deploy | да, заглушка остаётся |
| 6 и 9 | `up -d --no-deps` api | prod, ip, deploy | да |
| 8 | `run` CLI | prod, ip | нет |

Сборки frontend в этих шагах нет.

---

## Переменные окна

Файл на стенде: `${APP_ROOT}/var/${WINDOW_ID}/window.env`, режим `600`, не в git. Секретов в нём нет: ни паролей, ни URL с паролем, ни ключей. Содержимое файла в notes, логи и чат не копировать.

```bash
WINDOW_ID=pr25-0022-0023-YYYYMMDD
WINDOW_SHA=<полный sha main с зелёными ci и e2e>
PREV_SHA=
APP_ROOT=/path/to/app
PERIOD=ГГГГ-ММ
COMPANY_ID=<uuid организации стенда>
ACTOR_EMAIL=<email пользователя с finance write>
```

`PREV_SHA` до шага 2 пустой. `SSH_ALIAS` остаётся в оболочке, с которой запускают ssh, и в файл не пишется. `set -u` в командах не снимать: не заданная переменная обрывает шаг.

Каждая ssh-команда начинается с подключения этого файла. `APP_ROOT` и `WINDOW_ID` в аргументах нужны только чтобы найти файл; рабочие значения после точки берутся из него.

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
cd "${APP_ROOT}"
REMOTE
```

## Команды (не выполнять из CI)

### Бэкап БД до миграции

Дамп пишется в `/var/backups/finpilot/`, вне `${APP_ROOT}`. Checkout и повторная выкладка каталога приложения этот путь не затирают. Файл внутри `${APP_ROOT}` проверку не проходит. `pg_restore --list` идёт в уже запущенном контейнере `postgres` этого compose. Новый образ для проверки не скачивать.

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
cd "${APP_ROOT}"
TS=$(date -u +%Y%m%dT%H%M%SZ)
DUMP="/var/backups/finpilot/pre-0022-0023-${WINDOW_ID}-${TS}.dump"
case "${DUMP}" in
  "${APP_ROOT}"/*) echo "FAIL dump inside APP_ROOT"; exit 1;;
esac
install -d -m 700 /var/backups/finpilot
docker compose --env-file .env -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  exec -T postgres \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' \
  > "${DUMP}"
test -s "${DUMP}"
stat -c %s "${DUMP}"
chmod 600 "${DUMP}"
docker compose --env-file .env -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  cp "${DUMP}" postgres:/tmp/pre-0022-0023.dump
docker compose --env-file .env -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  exec -T postgres pg_restore --list /tmp/pre-0022-0023.dump \
  >/tmp/pre-0022-0023.list
docker compose --env-file .env -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  exec -T postgres rm -f /tmp/pre-0022-0023.dump
test -s /tmp/pre-0022-0023.list
rm -f /tmp/pre-0022-0023.list
sha256sum "${DUMP}" | awk '{print $1}' > "${DUMP}.sha256"
chmod 600 "${DUMP}.sha256"
printf 'backup_file=%s\n' "${DUMP}" >> "var/${WINDOW_ID}/notes.md"
echo "backup_ok ${DUMP}"
REMOTE
```

PASS шага 1: `backup_ok`, размер больше нуля, `pg_restore --list` без ошибки, путь не под `${APP_ROOT}`. Список объектов из `--list` в notes, git и чат не копировать. Иначе migrate не начинать.

Копия дампа вне VPS необязательна и делается после PASS, только этот файл и его sha256, на Mac владельца:

`DUMP_PATH` — значение `backup_file` из notes, один файл.

```bash
mkdir -p "${HOME}/finpilot-window-backups"
scp "${SSH_ALIAS}:${DUMP_PATH}" "${SSH_ALIAS}:${DUMP_PATH}.sha256" \
  "${HOME}/finpilot-window-backups/"
cd "${HOME}/finpilot-window-backups"
dump=$(basename "${DUMP_PATH}")
test "$(shasum -a 256 "${dump}" | awk '{print $1}')" = "$(cat "${dump}.sha256")"
echo "offsite_ok"
```

### Код на WINDOW_SHA

После PASS бэкапа. Грязное дерево — стоп, checkout не делать.

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
cd "${APP_ROOT}"
test -n "${WINDOW_SHA}"
if test -n "$(git status --short)"; then
  echo "FAIL dirty tree"
  exit 1
fi
prev=$(git rev-parse HEAD)
printf 'PREV_SHA=%s\n' "${prev}" >> "var/${WINDOW_ID}/notes.md"
python3 - "${prev}" <<'PY'
import sys
from pathlib import Path
import os
prev = sys.argv[1]
path = Path(os.environ["APP_ROOT"]) / "var" / os.environ["WINDOW_ID"] / "window.env"
lines = path.read_text().splitlines()
key = "PREV_SHA="
out = []
found = False
for line in lines:
    if line.startswith(key):
        out.append(key + prev)
        found = True
    else:
        out.append(line)
if not found:
    out.append(key + prev)
path.write_text("\n".join(out) + "\n")
path.chmod(0o600)
PY
git fetch origin
git checkout --detach "${WINDOW_SHA}"
test "$(git rev-parse HEAD)" = "${WINDOW_SHA}"
echo "code_ok ${WINDOW_SHA}"
REMOTE
```

PASS: `code_ok` и тот же SHA, на котором ci и e2e были success. Иначе сборку и migrate не начинать.

### Образ и остановка api, worker, beat

Шаг 2b начинать только если шаг 0 записал `registry_ok` и `pypi_ok`. Иначе не собирать образ на VPS.

Отдельного образа migrate в репозитории нет. api, worker, beat и одноразовый контейнер migrate — один тег `finpilot-api:0.2.0`, контекст `backend/`, как в Dockerfile (`uv sync --frozen --no-dev`). Postgres и redis не останавливать. Frontend и proxy с `c34328f` до `30491d5` не менялись (`git diff --stat` по `frontend/` и `infra/` пустой). Их в этом шаге не собирать. В notes уже есть `frontend_proxy=не менялись`. Если HEAD стенда из шага 0 не `c34328f` и повторный diff непустой, эту команду не запускать.

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
cd "${APP_ROOT}"
docker build --network=host -t finpilot-api:0.2.0 backend
heads=$(docker run --rm --entrypoint "" finpilot-api:0.2.0 \
  /app/.venv/bin/alembic heads)
printf '%s\n' "${heads}"
printf '%s\n' "${heads}" | grep -q '20261111_0023 (head)'
docker compose --env-file .env \
  -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  -f infra/docker-compose.prod.deploy.override.yml \
  stop api worker beat
running=$(docker compose --env-file .env \
  -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  -f infra/docker-compose.prod.deploy.override.yml \
  ps --services --filter status=running)
for name in api worker beat; do
  if printf '%s\n' "${running}" | grep -qx "${name}"; then
    echo "FAIL ${name} still running"
    exit 1
  fi
done
echo "images_ok"
REMOTE
```

PASS: в выводе heads есть `20261111_0023 (head)` и строка `images_ok`. Иначе migrate не начинать.

### Миграция и gate ревизии

Один прогон. `MIGRATION_DATABASE_URL` берётся из `.env` сервиса, в лог и notes его не писать. Сервиса `migrate` в compose нет: это `run` образа api.

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
cd "${APP_ROOT}"
docker compose --env-file .env \
  -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  -f infra/docker-compose.prod.deploy.override.yml \
  run --rm --no-deps --entrypoint "" api \
  /app/.venv/bin/alembic upgrade head
ver=$(docker compose --env-file .env \
  -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  exec -T postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -c "SELECT version_num FROM alembic_version;"')
printf 'alembic_version=%s\n' "${ver}" >> "var/${WINDOW_ID}/notes.md"
test "${ver}" = "20261111_0023"
echo "migrate_ok ${ver}"
REMOTE
```

Ожидание в логе upgrade (при baseline `20261107_0021`):

- `Running upgrade 20261107_0021 -> 20261110_0022`
- `Running upgrade 20261110_0022 -> 20261111_0023`

PASS: `migrate_ok 20261111_0023`. Если версия другая — стоп, api/worker/beat не запускать.

### Запуск после gate

Без `--build`: образ уже проверен на шаге 2b.

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
cd "${APP_ROOT}"
docker compose --env-file .env \
  -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  -f infra/docker-compose.prod.deploy.override.yml \
  up -d --no-build api worker beat frontend proxy
echo "up_ok"
REMOTE
```

### Health, compose up, туннель, acceptance

Запуск compose — команда выше, без повторного `--build`. Health и `staging_acceptance.py` — как в [runbook-staging-window-pr25-0022.md](runbook-staging-window-pr25-0022.md). Acceptance относится к шагу 10, не к migrate.

---

## Проверки **до** миграции

| Проверка | PASS |
| --- | --- |
| CI main на `WINDOW_SHA` | success, ci и e2e; playwright — прогон тестов |
| `git status --short` до checkout | пусто |
| `PREV_SHA` в notes и в `window.env` | записан до checkout |
| HEAD стенда | равен `WINDOW_SHA` |
| `alembic heads` внутри `finpilot-api:0.2.0` | `20261111_0023 (head)` |
| api, worker, beat перед migrate | остановлены |
| Бэкап в `/var/backups/finpilot/`, не в `${APP_ROOT}` | да |
| Размер дампа и `pg_restore --list` в контейнере postgres | размер > 0, list без ошибок |
| Долгие транзакции и место | count = 0; свободно ≥ 2× размера БД |
| Текущая ревизия alembic | `20261107_0021` **или** известная предыдущая (зафиксировать в notes) |
| `.env` не в git, `chmod 600` | да |
| Нет планов `FLUSHDB` | да |

---

## Проверки **после** migrate (head `20261111_0023`)

Номера пунктов ниже — проверки smoke, не номера шагов окна. Шаги окна заданы в разделе «Порядок шагов».

### 1. Версия Alembic

```sql
SELECT version_num FROM alembic_version;
```

Ожидание: `20261111_0023`.

### 2. Таблицы

```sql
SELECT to_regclass('public.import_source_fingerprints'),
       to_regclass('public.import_row_lineage'),
       to_regclass('public.reconciliation_run'),
       to_regclass('public.source_correction_finding');
SELECT to_regprocedure('app_expire_reconciliation_runs(timestamptz, integer)');
```

### 3. RLS (включая `source_correction_finding`)

```sql
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN (
    'import_source_fingerprints',
    'import_row_lineage',
    'reconciliation_run',
    'source_correction_finding'
  );
```

Ожидание: `relrowsecurity` и `relforcerowsecurity` = true; политики с `app_tenant()`.

### 4. Grants

Как для 0022 (fingerprint/lineage/run) **плюс** app SELECT/INSERT/UPDATE и worker SELECT/INSERT на `source_correction_finding` (см. миграцию 0023).

### 5. Smoke: provenance (синтетика)

Компания **ООО «Топ»**, CSV cash upload → commit → fingerprint ≥ 1, lineage ≥ 1 (SQL как в узком runbook 0022).

### 6. Smoke: коррекции (синтетика)

Через UI/API на стенде (не клиентские файлы):

1. **Дубль файла / duplicate_suspect:** провести тот же cash CSV дважды (разные имена файлов) или второй файл с пересекающимся `external_id`/`amount` — ожидание: запись в `source_correction_finding` с `kind = 'duplicate_suspect'`, commit обоих batch **успешен**.
2. **Пересечение периодов / period_overlap:** два cash-файла с датами в перекрывающихся диапазонах по одному кошельку — ожидание: `kind = 'period_overlap'`.

Записать в notes **`smoke_batch_id_a`**, **`smoke_batch_id_b`** (UUID из ответа upload/commit API).

```sql
SELECT id, kind, severity, import_batch_id, created_at
FROM source_correction_finding
WHERE import_batch_id IN (:smoke_batch_id_a, :smoke_batch_id_b)
ORDER BY created_at;
```

Ожидание: по каждому тестовому файлу — **конкретные** строки с ожидаемым `kind`; не полагаться на `count(*)` по всей таблице.

### 7. Логи API/worker

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
cd "${APP_ROOT}"
docker compose --env-file .env \
  -f infra/docker-compose.prod.yml \
  logs --since=30m api worker 2>&1 \
  | grep -E "import_provenance_failed|correction_scan_failed|ERROR|Traceback" || true
REMOTE
```

Ожидание: нет `import_provenance_failed` / `correction_scan_failed` на успешном smoke; нет необъяснимых ERROR.

### Флаг, образцы и CLI (шаги 6–9 окна, после smoke PASS)

Команды ниже CI не выполняет. В режиме Б их выполняет Cursor только после письменного разрешения на `WINDOW_SHA`.

**Образцы. Одна схема.** Клиентские выгрузки на стенд запрещены (решение 2026-10-27). Генератор `scripts/make_synthetic_persist_run_samples.py` лежит вне контекста `docker build ... backend`, в образ api не попадает и dev-зависимости не требует: это стандартная библиотека. Создавать файлы на машине владельца, в копии репозитория на `WINDOW_SHA`. На стенд копировать только `S1_synthetic.txt` и `S2_synthetic.xls` в `${APP_ROOT}/var/${WINDOW_ID}/synthetic/`. Фикстуры тестов, остальной `var/` и любой другой путь не копировать. Шаг проверяет запись прогона и права, не парсеры на реальных выгрузках.

**Почему на стенде заглушка xlrd.** Решение 2026-10-27 (FA-R03.2, пункт 2c, и FA-R03.2b/2c): `xlrd==2.0.1` только в dev-группе, в CI и prod её не ставить до отдельного процесса. Образ api собирается `uv sync --frozen --no-dev`, в постоянные зависимости и в слои образа библиотека не входит. В `STATE.json` ключ `xlrd_2_0_1` = `dev_dependency_accepted_not_in_ci_prod_yet`. `infra/docker-compose.prod.deploy.override.yml` ставит `UV_NO_SYNC=1`, чтобы `uv run` не доставил dev-группу, и монтирует `infra/stand-patches/xlrd_stub` поверх `site-packages/xlrd` у api, worker и beat. Импорт бросает `xls reading is disabled on the staging stand`. Постоянный процесс стенда .xls не читает. Клиентские выгрузки туда не кладут (то же решение 2026-10-27).

**Smoke-строка всё равно нужна.** `xlrd==2.0.1` не входит в образ. Wheel берётся по URL из `backend/uv.lock` (файлы `files.pythonhosted.org`), заранее на машине владельца, с проверкой sha256. На VPS во время окна пакет из сети не качается: одноразовый контейнер ставит локальный wheel с `--offline`. Образ `finpilot-api:0.2.0` и lockfile не менять, контейнер не коммитить, после запуска удалить (`--rm`). Deploy override в этот запуск не входит.

Включать флаг **только после** `alembic_version = 20261111_0023` и успешного smoke выше. До этого флаг `false`. Образ api собран на шаге 2b из `WINDOW_SHA`. `COMPANY_ID`, `PERIOD`, `ACTOR_EMAIL` читаются из `window.env`.

Переменная читается из `${APP_ROOT}/.env` на стенде (`env_file` сервиса `api` в compose). Файла `.env` в git нет.

Правка `.env` не печатает файл. Копия лежит вне `${APP_ROOT}`. В stdout только `flag_ok`, затем перезапуск api.

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
cd "${APP_ROOT}"
install -d -m 700 /var/backups/finpilot
backup="/var/backups/finpilot/dotenv.before-flag-${WINDOW_ID}"
cp -p .env "${backup}"
chmod 600 "${backup}"
python3 - <<'PY'
from pathlib import Path
path = Path(".env")
key = "RECONCILIATION_RUN_PERSIST_ENABLED"
wanted = "true"
out = []
found = False
for line in path.read_text().splitlines():
    if line.startswith(key + "="):
        out.append(f"{key}={wanted}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}={wanted}")
path.write_text("\n".join(out) + "\n")
path.chmod(0o600)
vals = [
    line.split("=", 1)[1]
    for line in path.read_text().splitlines()
    if line.startswith(key + "=")
]
if vals != [wanted]:
    raise SystemExit("FAIL flag")
print("flag_ok")
PY
docker compose --env-file .env \
  -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  -f infra/docker-compose.prod.deploy.override.yml \
  up -d --no-deps --no-build api
REMOTE
```

Что флаг делает и чего не делает:

- Включает запись append-only `reconciliation_run` в `reconcile_bank_card51_for_company` (finance write + подтверждённый email).
- **Не** превращает `GET /api/v1/companies/{id}/reconciliation/bank-card-51` в запись: осмотр остаётся без побочных эффектов.
- Публичного API и UI прогонов нет. Сам факт `true` в env строку не создаёт.
- Повторный прогон добавляет вторую строку (`supersedes_run_id`), без UPDATE. Для smoke окна нужен один запуск с `--yes`.
- Сбой INSERT пишется в лог как `reconciliation_run_persist_failed` с `company_id` и периодом, без текстов назначений и email.

На машине владельца, в каталоге репозитория на `WINDOW_SHA`. `PERIOD` совпадает с `--period` CLI:

```bash
python3 scripts/make_synthetic_persist_run_samples.py \
  --window-id "${WINDOW_ID}" \
  --period "${PERIOD}"
```

На стенд — только эти два файла:

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
mkdir -p "${APP_ROOT}/var/${WINDOW_ID}/synthetic"
REMOTE
scp "var/${WINDOW_ID}/synthetic/S1_synthetic.txt" \
  "var/${WINDOW_ID}/synthetic/S2_synthetic.xls" \
  "${SSH_ALIAS}:${APP_ROOT}/var/${WINDOW_ID}/synthetic/"
```

Другой локальный путь в `scp` не подставлять. После копирования в каталоге ровно два имени. `SAMPLES_DIR` = `${APP_ROOT}/var/${WINDOW_ID}/synthetic`. Каталог в git не попадает.

Перед CLI записать id образа. После обоих запусков id должен совпасть: слой образа не пересобирался и контейнер в образ не коммитился.

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
cd "${APP_ROOT}"
docker image inspect finpilot-api:0.2.0 --format '{{.Id}} {{json .RepoDigests}}'
REMOTE
```

Wheel готовится на машине владельца, не на VPS. URL и sha256 — строка wheel в `backend/uv.lock` для `xlrd` 2.0.1. Ожидаемый sha256: `6a33ee89877bd9abc1158129f6e94be74e2679636b8a205b43b85206c3f0bbdd`. Если сумма не сошлась, файл на стенд не копировать.

```bash
curl -fsSL -o xlrd-2.0.1-py2.py3-none-any.whl \
  "https://files.pythonhosted.org/packages/a6/0c/c2a72d51fe56e08a08acc85d13013558a2d793028ae7385448a6ccdfae64/xlrd-2.0.1-py2.py3-none-any.whl"
test "$(shasum -a 256 xlrd-2.0.1-py2.py3-none-any.whl | awk '{print $1}')" \
  = "6a33ee89877bd9abc1158129f6e94be74e2679636b8a205b43b85206c3f0bbdd"
printf '%s\n' 'xlrd==2.0.1 --hash=sha256:6a33ee89877bd9abc1158129f6e94be74e2679636b8a205b43b85206c3f0bbdd' \
  > xlrd-2.0.1.txt
```

На стенд только wheel и этот файл хеша:

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
mkdir -p "${APP_ROOT}/var/${WINDOW_ID}/xlrd"
REMOTE
scp xlrd-2.0.1-py2.py3-none-any.whl xlrd-2.0.1.txt \
  "${SSH_ALIAS}:${APP_ROOT}/var/${WINDOW_ID}/xlrd/"
```

Одноразовый контейнер: prod и ip override, **без** deploy override. База — уже собранный `finpilot-api:0.2.0`. `uv pip install --offline --no-index --find-links` берёт wheel с диска и сверяет хеш. `uv run --no-sync` не пересинхронизирует lock. `--rm` удаляет контейнер. Постоянный api заглушку не теряет. Сеть до PyPI этому шагу не нужна.

Пробный запуск (без `--yes`): считает сверку, печатает счётчики и `persist=skipped`, в БД не пишет. `--as-user` — email пользователя с finance write и подтверждённым email. В notes не копировать полный email: CLI печатает маску, в SQL смотреть `created_by_user_id`.

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
cd "${APP_ROOT}"
test -n "${COMPANY_ID}" && test -n "${PERIOD}" && test -n "${ACTOR_EMAIL}"
docker compose --env-file .env \
  -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  run --rm --no-deps \
  -e COMPANY_ID -e PERIOD -e ACTOR_EMAIL \
  -v "${APP_ROOT}/var/${WINDOW_ID}/synthetic:/samples:ro" \
  -v "${APP_ROOT}/var/${WINDOW_ID}/xlrd:/wheels:ro" \
  api \
  sh -c 'uv pip install --python /app/.venv/bin/python \
    --offline --no-index --find-links /wheels \
    --require-hashes --only-binary=xlrd \
    -r /wheels/xlrd-2.0.1.txt \
    && uv run --no-sync python -m app.tools.fa_r03_persist_run \
    --company-id "$COMPANY_ID" \
    --period "$PERIOD" \
    --as-user "$ACTOR_EMAIL" \
    /samples'
REMOTE
```

Ожидание пробного запуска: exit 0, в stdout `persist=skipped` и счётчики, без контрагентов, назначений и полного email. `count(*)` по `reconciliation_run` для этого `company_id` не вырос.

Запуск с записью — тот же контейнер, в конце аргументов `--yes`. Флаг в env уже `true`, иначе CLI отказывает и ничего не пишет.

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
cd "${APP_ROOT}"
test -n "${COMPANY_ID}" && test -n "${PERIOD}" && test -n "${ACTOR_EMAIL}"
docker compose --env-file .env \
  -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  run --rm --no-deps \
  -e COMPANY_ID -e PERIOD -e ACTOR_EMAIL \
  -v "${APP_ROOT}/var/${WINDOW_ID}/synthetic:/samples:ro" \
  -v "${APP_ROOT}/var/${WINDOW_ID}/xlrd:/wheels:ro" \
  api \
  sh -c 'uv pip install --python /app/.venv/bin/python \
    --offline --no-index --find-links /wheels \
    --require-hashes --only-binary=xlrd \
    -r /wheels/xlrd-2.0.1.txt \
    && uv run --no-sync python -m app.tools.fa_r03_persist_run \
    --company-id "$COMPANY_ID" \
    --period "$PERIOD" \
    --as-user "$ACTOR_EMAIL" \
    --yes \
    /samples'
REMOTE
```

Ожидание: exit 0, одна строка `run_id=…` и `persist=written`. Повторно снять id образа: он равен значению до запусков. `docker ps -a` не показывает оставшийся контейнер этого `run`.

**PASS этого шага:** ровно одна новая строка `reconciliation_run` (`run_kind = bank_card_51`, count вырос на 1), `id` совпадает с напечатанным `run_id`, `created_by_user_id` — пользователь из `--as-user`, `supersedes_run_id` пуст. Ноль строк или строка от другого пользователя — FAIL шага, не обход через клиентский xls и не правка образа api.

Проверка одной строки (id из stdout, без дампа JSON):

```sql
SELECT count(*) FROM reconciliation_run
 WHERE company_id = :company_id AND run_kind = 'bank_card_51';
SELECT id, run_kind, period_year, period_month,
       created_by_user_id, supersedes_run_id
  FROM reconciliation_run
 WHERE id = :run_id;
```

Ожидание SQL: count на 1 больше, чем до `--yes`. `id` совпадает с `run_id`, `created_by_user_id` — пользователь из `--as-user`, `supersedes_run_id` пуст. В notes писать `run_id` и id образа до/после, без email.

Stdout одноразового CLI уже на терминале окна: там нет `reconciliation_run_persist_failed`, `reconciliation_run_cli_failed`, назначений, контрагентов и полного email. Контейнер с `--rm` в `docker logs` не остаётся. Ниже — логи постоянного api (он с заглушкой и эту строку не писал):

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
cd "${APP_ROOT}"
docker compose --env-file .env \
  -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  -f infra/docker-compose.prod.deploy.override.yml \
  logs --since=30m api 2>&1 \
  | grep -E "reconciliation_run_persist_failed|reconciliation_run_cli_failed|ERROR|Traceback" || true
REMOTE
```

Шаг 9 по умолчанию возвращает флаг в `false` и перезапускает api. Содержимое `.env` не печатается. Оставить `true` можно только отдельным явным решением владельца, записанным до этого шага. Без такой записи выполнять команду ниже.

```bash
ssh "${SSH_ALIAS}" bash -s -- "${APP_ROOT}" "${WINDOW_ID}" <<'REMOTE'
set -euo pipefail
APP_ROOT=$1
WINDOW_ID=$2
set -a
. "${APP_ROOT}/var/${WINDOW_ID}/window.env"
set +a
cd "${APP_ROOT}"
install -d -m 700 /var/backups/finpilot
backup="/var/backups/finpilot/dotenv.before-reset-${WINDOW_ID}"
cp -p .env "${backup}"
chmod 600 "${backup}"
python3 - <<'PY'
from pathlib import Path
path = Path(".env")
key = "RECONCILIATION_RUN_PERSIST_ENABLED"
wanted = "false"
out = []
found = False
for line in path.read_text().splitlines():
    if line.startswith(key + "="):
        out.append(f"{key}={wanted}")
        found = True
    else:
        out.append(line)
if not found:
    out.append(f"{key}={wanted}")
path.write_text("\n".join(out) + "\n")
path.chmod(0o600)
vals = [
    line.split("=", 1)[1]
    for line in path.read_text().splitlines()
    if line.startswith(key + "=")
]
if vals != [wanted]:
    raise SystemExit("FAIL flag")
print("flag_ok")
PY
docker compose --env-file .env \
  -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  -f infra/docker-compose.prod.deploy.override.yml \
  up -d --no-deps --no-build api
REMOTE
```

В `var/${WINDOW_ID}/notes.md` записать `persist_flag=reset_false` или, если отдельное решение было, `persist_flag=left_true`. Рядом `run_id`. Без email и без сырого лога. Повтор CLI с `--yes` при оставленном `true` создаст вторую строку.

Откат этого шага:

- Флаг: `RECONCILIATION_RUN_PERSIST_ENABLED=false` и перезапуск api. Уже записанную строку не удалять (`reconciliation_run` append-only).
- Если строка есть, `alembic downgrade` не делать — сработает `downgrade_blocked`. Убрать строку можно только восстановлением из бэкапа `pre-0022-0023-*`.
- Откат кода на SHA раньше появления CLI (`dca0cbd`) убирает команду, строку в БД не убирает. Откат кода этого окна — на SHA, записанный до checkout `WINDOW_SHA`.

В `notes.md`: `persist_flag`, момент перезапуска api, `run_id` и счётчики из stdout. Без PII.

### Приёмка PR #25 (шаг 10 окна)

`staging_acceptance.py`, tenant B, webhook — [runbook-staging-acceptance.md](runbook-staging-acceptance.md).

---

## Критерии отката

| Ситуация | Действие |
| --- | --- |
| **Migrate не завершился** / api не стартует | Откат **кода** на `PREV_SHA`; БД без изменений (если migrate не commit) — повтор после fix |
| **0022/0023 применены, продукт неверен** | **Не** `alembic downgrade`, если есть строки в `reconciliation_run`, provenance или **`source_correction_finding`** — сработает `downgrade_blocked` |
| **Откат схемы при пустых новых таблицах** | Только если **все** новые таблицы пусты: последовательный downgrade до `20261107_0021`; затем откат кода |
| **Данные в provenance / corrections / run** | **Только восстановление из бэкапа** `pre-0022-0023-*` — **не** полагаться на downgrade на боевых данных |
| **Флаг прогона включён, smoke CLI не нужен или неуспешен** | Вернуть `RECONCILIATION_RUN_PERSIST_ENABLED=false` и перезапустить api. Уже созданную строку не удалять |
| **Нужно убрать smoke-строку `reconciliation_run`** | Только бэкап `pre-0022-0023-*`. DELETE приложению недоступен, downgrade при непустой таблице заблокирован |
| Rate limit / 429 | `redis-cli DEL 'register:<ip>'` — точечно |
| Критический FAIL | Остановить приёмку; не трогать prod |

Зафиксировать в `var/${WINDOW_ID}/notes.md`: `backup_file`, `alembic_before`, `alembic_after`, `smoke_fingerprint`, `smoke_corrections`, `rollback: none|code_only|db_restore`.

---

## Чек-лист приёмки владельцем

- [ ] WINDOW_ID, `WINDOW_SHA`, `PREV_SHA`, время начала/конца migrate.
- [ ] Бэкап до migrate вне `${APP_ROOT}`: путь, размер > 0, `pg_restore --list` внутри контейнера postgres без ошибок.
- [ ] До checkout дерево было чистым. В образе `alembic heads` показал `20261111_0023`. api, worker и beat на время migrate были остановлены.
- [ ] Alembic **`20261111_0023`** подтверждён.
- [ ] RLS/grants 0022+0023 — PASS.
- [ ] Smoke provenance — PASS.
- [ ] Smoke коррекций (duplicate + period_overlap) — PASS или skip с причиной.
- [ ] Логи без `import_provenance_failed` / `correction_scan_failed` на smoke.
- [ ] Флаг выставлен в `true` правкой `.env` с копией вне `${APP_ROOT}`, в логе только `flag_ok`, содержимое `.env` не печаталось. Api перезапущен после smoke.
- [ ] На стенде только `${APP_ROOT}/var/${WINDOW_ID}/synthetic/` с двумя файлами генератора. Другие файлы туда не копировались.
- [ ] CLI без `--yes` в одноразовом контейнере не создал строку.
- [ ] CLI с `--yes`: ровно одна новая строка, автор — пользователь из `--as-user`. Id образа `finpilot-api:0.2.0` до и после совпал, контейнер удалён.
- [ ] В stdout и логах нет `reconciliation_run_persist_failed` / `reconciliation_run_cli_failed` и нет полного email.
- [ ] Флаг возвращён в `false`, api перезапущен. `true` оставлен только если есть отдельное явное решение владельца.
- [ ] PR #25 acceptance — PASS.
- [ ] STATE: `migration_applied_staging` для **0022 и 0023** — только после подписи окна.
- [ ] Решение: **PASS** / **FAIL** + план.

---

## Критерии PASS / FAIL окна

**PASS** — SHA main с 0023, migrate head, health 200, SQL + smoke provenance + smoke коррекций, acceptance, артефакты в `var/${WINDOW_ID}/`.

**FAIL** — любой критичный пункт + отсутствие бэкапа до migrate.

---

## Связанные записи

- STATE: `fa_r03_3_min`, `fa_r03_4_v1`, `infra-staging-rate-limit`.
- Scope: [FA-R03.3-implementation-scope.md](roadmap/FA-R03.3-implementation-scope.md), [FA-R03.4-corrections-design.md](roadmap/FA-R03.4-corrections-design.md).
- Репетиция: `scripts/rehearse_staging_migrations_0022_0023.py`, [migration-integration-test-checklist.md](migration-integration-test-checklist.md).
- Миграции: `backend/alembic/versions/20261110_0022_*`, `20261111_0023_*`.
