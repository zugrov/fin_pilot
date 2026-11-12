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

Перед окном записать в `var/${WINDOW_ID}/notes.md` строку `WINDOW_SHA=<полный sha>`. На сервере `git fetch && git checkout --detach "${WINDOW_SHA}"`. `git rev-parse HEAD` обязан совпасть с `WINDOW_SHA`. Нижняя граница вида «не старее коммита» не используется: на стенд попадает этот SHA и только он.

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

В `baseline.json` записать `long_tx_count`, `db_bytes`, `avail_backup_bytes`, `avail_docker_bytes`. `long_tx_count` должен быть 0. `avail_backup_bytes` и `avail_docker_bytes` — каждый не меньше `2 * db_bytes`. Иначе окно остановить до бэкапа и migrate.

**Повтор 2026-11-10:** `ssh -o ConnectTimeout=10 … true` → **timeout**, без повторных попыток. Факт с VPS **не подтверждён**; сценарий **A** (`20261027_0017`) по-прежнему из STATE до `baseline.json` владельца.

Если preflight SSH не проходит или шаг 0 не дал `alembic_version`, объём БД, `long_tx_count = 0` и место ≥ 2× размера БД — окно migrate **не начинать**.

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
- [ ] Зафиксирован **SHA до окна** (откат кода без отката БД).

---

## Порядок шагов (обязательная последовательность)

0. **Baseline, только чтение.** Ревизия, долгие транзакции, место ≥ 2× размера БД. FAIL — стоп.
1. **Бэкап** в `/var/backups/finpilot/`, затем размер, `pg_restore --list` и проверка, что путь вне `${APP_ROOT}`. Без PASS migrate не начинать.
2. **Код:** checkout точного `WINDOW_SHA` из notes. HEAD стенда равен этой строке. Миграции 0022/0023 уже в main с `7258e2b`.
3. **Миграция:** один прогон `alembic upgrade head` из **migrate**-контейнера с `MIGRATION_DATABASE_URL`.
4. **Пересборка и перезапуск:** `docker compose … up -d --build api worker beat frontend proxy` (три override — см. базовый runbook). Каталог `${APP_ROOT}` эта пересборка может заменить, поэтому дамп шага 1 там не лежит.
5. **Smoke post-migrate:** health, revision **0023**, таблицы/RLS, worker grants, import → fingerprint/lineage + **коррекции** (§ ниже).
6. **Флаг** `RECONCILIATION_RUN_PERSIST_ENABLED=true` в `.env` стенда и перезапуск api — только если шаг 5 **PASS**.
7. **Образцы:** одна схема ниже. На стенд только `var/${WINDOW_ID}/synthetic/`.
8. **CLI:** пробный запуск, затем `--yes`, одна новая строка.
9. **Флаг обратно в false** и перезапуск api. `true` оставить только отдельным явным решением владельца.
10. **Приёмка PR #25 и ручной UI** — UI всегда владелец.
11. **Завершение:** дамп после окна, отчёт `var/${WINDOW_ID}/` (`baseline.json`, `migrate_timing.txt`, smoke batch id), остановка VPS по политике.

---

## Команды (не выполнять из CI)

### Бэкап БД до миграции

Дамп пишется в `/var/backups/finpilot/`, вне `${APP_ROOT}`. Пересборка шага 4 идёт из каталога приложения и может его заменить. Файл внутри `${APP_ROOT}` проверку не проходит.

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  TS=$(date -u +%Y%m%dT%H%M%SZ)
  DUMP="/var/backups/finpilot/pre-0022-0023-${WINDOW_ID}-${TS}.dump"
  case "${DUMP}" in
    "${APP_ROOT}"/*) echo "FAIL dump inside APP_ROOT"; exit 1;;
  esac
  mkdir -p /var/backups/finpilot
  docker compose --env-file .env -f infra/docker-compose.prod.yml \
    -f infra/docker-compose.prod.ip.override.yml \
    exec -T postgres \
    pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --format=custom \
    > "${DUMP}"
  test -s "${DUMP}"
  stat -c %s "${DUMP}"
  docker run --rm -v /var/backups/finpilot:/dumps:ro postgres:16.6-bookworm \
    pg_restore --list "/dumps/$(basename "${DUMP}")" >/tmp/pre-0022-0023.list
  test -s /tmp/pre-0022-0023.list
  rm -f /tmp/pre-0022-0023.list
  echo "backup_ok ${DUMP}"'
```

PASS шага 1: команда завершилась с `backup_ok`, размер в байтах больше нуля, `pg_restore --list` завершился без ошибки, путь дампа не под `${APP_ROOT}`. Имя, размер и путь записать в notes. Список объектов из `--list` в notes, git и чат не копировать. Если любой пункт не сошёлся — migrate не начинать.

### Код на WINDOW_SHA

После PASS бэкапа и до migrate. `WINDOW_SHA` уже записан в notes и экспортирован в оболочке стенда.

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  git fetch origin
  git checkout --detach "${WINDOW_SHA}"
  test "$(git rev-parse HEAD)" = "${WINDOW_SHA}"
  echo "code_ok ${WINDOW_SHA}"'
```

PASS: строка `code_ok` и тот же SHA, на котором ci и e2e были success. Иначе migrate не начинать.

Migrate запускать только после PASS шагов 1 и 2. Иначе стоп.

### Миграция (одноразовый migrate-контейнер)

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  docker compose --env-file .env \
    -f infra/docker-compose.prod.yml \
    -f infra/docker-compose.prod.ip.override.yml \
    run --rm migrate alembic upgrade head'
```

Ожидание в логе (при baseline `20261107_0021`):

- `Running upgrade 20261107_0021 -> 20261110_0022`
- `Running upgrade 20261110_0022 -> 20261111_0023`

### Health, compose up, туннель, acceptance

Как в [runbook-staging-window-pr25-0022.md](runbook-staging-window-pr25-0022.md) (§ Команды): compose up, health, `staging_acceptance.py`.

---

## Проверки **до** миграции

| Проверка | PASS |
| --- | --- |
| CI main на `WINDOW_SHA` | success, ci и e2e; playwright — прогон тестов |
| HEAD стенда | равен `WINDOW_SHA` из notes |
| Бэкап в `/var/backups/finpilot/`, не в `${APP_ROOT}` | да |
| Размер дампа и `pg_restore --list` | размер > 0, list без ошибок |
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
ssh "${SSH_ALIAS}" 'cd "${APP_ROOT}" && docker compose --env-file .env \
  -f infra/docker-compose.prod.yml logs --since=30m api worker 2>&1 \
  | grep -E "import_provenance_failed|correction_scan_failed|ERROR|Traceback" || true'
```

Ожидание: нет `import_provenance_failed` / `correction_scan_failed` на успешном smoke; нет необъяснимых ERROR.

### Флаг, образцы и CLI (шаги 6–9 окна, после smoke PASS)

Команды ниже CI не выполняет. В режиме Б их выполняет Cursor только после письменного разрешения на `WINDOW_SHA`.

**Образцы. Одна схема.** Клиентские выгрузки на стенд запрещены (решение 2026-10-27: только локально у владельца, не git, не staging, не чат). Генератор — `scripts/make_synthetic_persist_run_samples.py`. Он пишет два файла: `S1_synthetic.txt` и `S2_synthetic.xls`. Где генерировать: на машине владельца в копии репозитория `WINDOW_SHA` либо в одноразовом контейнере, которому на запись смонтирован только каталог синтетики. Куда класть на стенде: `${APP_ROOT}/var/${WINDOW_ID}/synthetic/`. Если файлы родились локально, на стенд копируется только этот каталог (эти два файла), не остальной `var/`, не фикстуры тестов и не любой другой путь. Готового генератора в тестах нет: фикстуры CLI кладут произвольные байты и подменяют расчёт. Шаг проверяет запись прогона и права, а не корректность парсеров на реальных данных.

**Почему на стенде заглушка xlrd.** Решение 2026-10-27 (FA-R03.2, пункт 2c, и FA-R03.2b/2c): `xlrd==2.0.1` только в dev-группе, в CI и prod её не ставить до отдельного процесса. Образ api собирается `uv sync --frozen --no-dev`, в постоянные зависимости и в слои образа библиотека не входит. В `STATE.json` ключ `xlrd_2_0_1` = `dev_dependency_accepted_not_in_ci_prod_yet`. `infra/docker-compose.prod.deploy.override.yml` ставит `UV_NO_SYNC=1`, чтобы `uv run` не доставил dev-группу, и монтирует `infra/stand-patches/xlrd_stub` поверх `site-packages/xlrd` у api, worker и beat. Импорт бросает `xls reading is disabled on the staging stand`. Постоянный процесс стенда .xls не читает. Клиентские выгрузки туда не кладут (то же решение 2026-10-27).

**Smoke-строка всё равно нужна.** `xlrd==2.0.1` ставится только в одноразовый контейнер CLI и только на синтетические файлы. Образ `finpilot-api:0.2.0` и lockfile не менять, контейнер не коммитить в образ, после запуска удалить (`--rm`). Deploy override в этот запуск не входит: с ним заглушка перекрыла бы только что поставленный пакет.

Включать **только после** `alembic_version = 20261111_0023` и успешного smoke выше (provenance, коррекции, логи без `import_provenance_failed` / `correction_scan_failed`). До этого в env api флаг отсутствует или равен `false` (значение по умолчанию в коде). Образ api собран на `WINDOW_SHA` (шаг 4), иначе модуля CLI в контейнере нет. `SAMPLES_DIR`, `COMPANY_ID`, `PERIOD`, `ACTOR_EMAIL` задаются в оболочке на стенде, не в git.

Переменная читается из `${APP_ROOT}/.env` на стенде (`env_file` сервиса `api` в compose). Файла `.env` в git нет.

```bash
# в ${APP_ROOT}/.env на стенде, не в git
RECONCILIATION_RUN_PERSIST_ENABLED=true
```

Перезапуск **только api**, тем же набором compose, что и окно, чтобы процесс перечитал env:

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  docker compose --env-file .env \
    -f infra/docker-compose.prod.yml \
    -f infra/docker-compose.prod.ip.override.yml \
    -f infra/docker-compose.prod.deploy.override.yml \
    up -d --no-deps api'
```

Что флаг делает и чего не делает:

- Включает запись append-only `reconciliation_run` в `reconcile_bank_card51_for_company` (finance write + подтверждённый email).
- **Не** превращает `GET /api/v1/companies/{id}/reconciliation/bank-card-51` в запись: осмотр остаётся без побочных эффектов.
- Публичного API и UI прогонов нет. Сам факт `true` в env строку не создаёт.
- Повторный прогон добавляет вторую строку (`supersedes_run_id`), без UPDATE. Для smoke окна нужен один запуск с `--yes`.
- Сбой INSERT пишется в лог как `reconciliation_run_persist_failed` с `company_id` и периодом, без текстов назначений и email.

`PERIOD` совпадает с `--period` CLI. Локально у владельца, в каталоге репозитория на `WINDOW_SHA`:

```bash
python3 scripts/make_synthetic_persist_run_samples.py \
  --window-id "${WINDOW_ID}" \
  --period "${PERIOD}"
```

На стенд — только этот каталог:

```bash
ssh "${SSH_ALIAS}" "mkdir -p '${APP_ROOT}/var/${WINDOW_ID}/synthetic'"
scp "var/${WINDOW_ID}/synthetic/S1_synthetic.txt" \
  "var/${WINDOW_ID}/synthetic/S2_synthetic.xls" \
  "${SSH_ALIAS}:${APP_ROOT}/var/${WINDOW_ID}/synthetic/"
```

Другой локальный путь в `scp` не подставлять. Тот же результат без копирования с машины владельца: одноразовый контейнер пишет сразу в каталог стенда. На запись смонтирован только он.

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  mkdir -p "var/${WINDOW_ID}/synthetic"
  docker compose --env-file .env \
    -f infra/docker-compose.prod.yml \
    -f infra/docker-compose.prod.ip.override.yml \
    run --rm --no-deps \
    -v "${APP_ROOT}/scripts/make_synthetic_persist_run_samples.py:/tmp/make_synthetic.py:ro" \
    -v "${APP_ROOT}/var/${WINDOW_ID}/synthetic:/out/${WINDOW_ID}/synthetic" \
    api \
    python /tmp/make_synthetic.py \
      --window-id "${WINDOW_ID}" \
      --period "${PERIOD}" \
      --root /out'
```

Выбирается один из двух запусков, не оба. После него в каталоге ровно `S1_synthetic.txt` и `S2_synthetic.xls`. `SAMPLES_DIR` = `${APP_ROOT}/var/${WINDOW_ID}/synthetic`. Каталог в git не попадает.

Перед CLI записать id образа. После обоих запусков id должен совпасть: слой образа не пересобирался и контейнер в образ не коммитился.

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  docker image inspect finpilot-api:0.2.0 --format "{{.Id}} {{json .RepoDigests}}"'
```

Файл хешей — во `var/${WINDOW_ID}/`, не в git. Хеш wheel — из `backend/uv.lock` для `xlrd` 2.0.1. Второй хеш — sdist из того же lock; `--only-binary=xlrd` его не скачивает, но `--require-hashes` сверяет тот артефакт, который реально ставится.

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  mkdir -p "var/${WINDOW_ID}"
  cat > "var/${WINDOW_ID}/xlrd-2.0.1.txt" <<EOF
xlrd==2.0.1 --hash=sha256:6a33ee89877bd9abc1158129f6e94be74e2679636b8a205b43b85206c3f0bbdd --hash=sha256:f72f148f54442c6b056bf931dbc34f986fd0c3b0b6b5a58d013c9aef274d0c88
EOF'
```

Одноразовый контейнер: те же prod и ip override, **без** `docker-compose.prod.deploy.override.yml`. База — уже собранный `finpilot-api:0.2.0`. `uv pip install` пишет пакет в venv контейнера, `uv run --no-sync` не пересинхронизирует lock и не выкидывает xlrd. `--rm` удаляет контейнер вместе с этим venv. Постоянный api/worker/beat заглушку не теряют.

Пробный запуск (без `--yes`): считает сверку, печатает счётчики и `persist=skipped`, в БД не пишет. `--as-user` — email пользователя с finance write и подтверждённым email. В notes не копировать полный email: CLI печатает маску, в SQL смотреть `created_by_user_id`.

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  docker compose --env-file .env \
    -f infra/docker-compose.prod.yml \
    -f infra/docker-compose.prod.ip.override.yml \
    run --rm --no-deps \
    -v "${SAMPLES_DIR}:/samples:ro" \
    -v "${APP_ROOT}/var/${WINDOW_ID}/xlrd-2.0.1.txt:/tmp/xlrd-2.0.1.txt:ro" \
    api \
    sh -c "uv pip install --python /app/.venv/bin/python \
      --require-hashes --only-binary=xlrd \
      -r /tmp/xlrd-2.0.1.txt \
      && uv run --no-sync python -m app.tools.fa_r03_persist_run \
      --company-id \"${COMPANY_ID}\" \
      --period \"${PERIOD}\" \
      --as-user \"${ACTOR_EMAIL}\" \
      /samples"'
```

Ожидание пробного запуска: exit 0, в stdout `persist=skipped` и счётчики, без контрагентов, назначений и полного email. `count(*)` по `reconciliation_run` для этого `company_id` не вырос.

Запуск с записью — тот же контейнер, в конце аргументов `--yes`. Флаг в env уже `true`, иначе CLI отказывает и ничего не пишет.

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  docker compose --env-file .env \
    -f infra/docker-compose.prod.yml \
    -f infra/docker-compose.prod.ip.override.yml \
    run --rm --no-deps \
    -v "${SAMPLES_DIR}:/samples:ro" \
    -v "${APP_ROOT}/var/${WINDOW_ID}/xlrd-2.0.1.txt:/tmp/xlrd-2.0.1.txt:ro" \
    api \
    sh -c "uv pip install --python /app/.venv/bin/python \
      --require-hashes --only-binary=xlrd \
      -r /tmp/xlrd-2.0.1.txt \
      && uv run --no-sync python -m app.tools.fa_r03_persist_run \
      --company-id \"${COMPANY_ID}\" \
      --period \"${PERIOD}\" \
      --as-user \"${ACTOR_EMAIL}\" \
      --yes \
      /samples"'
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
ssh "${SSH_ALIAS}" 'cd "${APP_ROOT}" && docker compose --env-file .env \
  -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  -f infra/docker-compose.prod.deploy.override.yml \
  logs --since=30m api 2>&1 \
  | grep -E "reconciliation_run_persist_failed|reconciliation_run_cli_failed|ERROR|Traceback" || true'
```

Рекомендация владельца для шага 9: вернуть `RECONCILIATION_RUN_PERSIST_ENABLED=false` и перезапустить api тем же `up -d --no-deps api`. Так следующий вызов сверки не допишет строку. Оставить `true` можно только отдельным явным решением владельца, записанным до этого шага. Без такой записи шаг 9 выполняет возврат в `false`.

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
| **Migrate не завершился** / api не стартует | Откат **кода** на SHA до pull; БД без изменений (если migrate не commit) — повтор после fix |
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

- [ ] WINDOW_ID, `WINDOW_SHA` (полный SHA, ci и e2e success), время начала/конца migrate.
- [ ] Бэкап до migrate вне `${APP_ROOT}`: путь, размер > 0, `pg_restore --list` без ошибок.
- [ ] Alembic **`20261111_0023`** подтверждён.
- [ ] RLS/grants 0022+0023 — PASS.
- [ ] Smoke provenance — PASS.
- [ ] Smoke коррекций (duplicate + period_overlap) — PASS или skip с причиной.
- [ ] Логи без `import_provenance_failed` / `correction_scan_failed` на smoke.
- [ ] `RECONCILIATION_RUN_PERSIST_ENABLED=true` в `.env` стенда (не в git) и перезапуск api — только после smoke выше.
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
