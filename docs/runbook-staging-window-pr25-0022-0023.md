# Окно деплоя на стенд · PR #25 + миграции `20261110_0022` и `20261111_0023`

**Назначение:** плановое окно выката на VPS **уже слитых** изменений:

- [PR #25](https://github.com/zugrov/fin_pilot/pull/25) — rate limit за Caddy, compose override, `staging_acceptance.py` (squash → `c34328f…`).
- [PR #34](https://github.com/zugrov/fin_pilot/pull/34) — **FA-R03.3-min**: fingerprint, lineage, `reconciliation_run`, миграция **`20261110_0022`** (product squash → `0fc224d…`).
- **FA-R03.4 v1** в **main**: `source_correction_finding`, миграция **`20261111_0023`** (merge `7258e2b…`).

**Деплой:** весь **main**; после migrate ожидается **`alembic head = 20261111_0023`**.

**Команды ниже — только для копирования. Агент/CI/автоматизация их не выполняет.**

**Базовые runbook:** [runbook-staging-window.md](runbook-staging-window.md), [runbook-staging-acceptance.md](runbook-staging-acceptance.md), [runbook-staging.md](runbook-staging.md).  
**Устаревшие:** [runbook-staging-window-pr25.md](runbook-staging-window-pr25.md), [runbook-staging-window-pr25-0022.md](runbook-staging-window-pr25-0022.md) — заменены этим документом.

---

## Версии (git)

| Объект | SHA / ссылка |
| --- | --- |
| **main на момент подготовки runbook** | `1be20626d6957cf2bd192af3e428f99bc190c056` |
| Минимум для PR #25 (rate limit) | `c34328f1873c636c4c23f5eb1e545cdc774e585f` |
| Минимум для FA-R03.3-min + migration 0022 | `0fc224d5eb39355a0911e1fb61a9024eb6307a14` |
| Минимум для FA-R03.4 v1 + migration 0023 | `7258e2bb83997066ba1b541e737771078f6e628` |
| **Рекомендуемый выкат** | **main** `a0d5ac7…` (head схемы **0023**) |

Перед окном на сервере: `git fetch && git checkout main && git pull`; `git rev-parse HEAD` ≥ `7258e2b` для миграции 0023 и кода коррекций.

CI **main** на выбранном SHA — **success** (backend, frontend, playwright).

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

**Вне этого окна:** `persist_reconciliation_run` из сверки, cron retention, сторно/FX, UI коррекций, деплой без бэкапа.

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
  "SELECT pg_size_pretty(pg_database_size(current_database()));"

df -h
free -m
ls -la "${APP_ROOT}/var/backups"
```

**Повтор 2026-11-10:** `ssh -o ConnectTimeout=10 … true` → **timeout**, без повторных попыток. Факт с VPS **не подтверждён**; сценарий **A** (`20261027_0017`) по-прежнему из STATE до `baseline.json` владельца.

Если preflight SSH не проходит — окно migrate **не начинать**, пока шаг 0 не даст `alembic_version` и объём таблиц.

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

1. **До касания продакшн-данных:** снять **бэкап БД** (pg_dump или согласованный snapshot VPS).
2. **Обновление кода:** `git pull` → SHA ≥ `7258e2b` (рекомендуется полный main `a0d5ac7…`).
3. **Миграция:** один прогон `alembic upgrade head` из **migrate**-контейнера/job с `MIGRATION_DATABASE_URL`.
4. **Пересборка и перезапуск:** `docker compose … up -d --build api worker beat frontend proxy` (три override — см. базовый runbook).
5. **Smoke post-migrate:** health, revision **0023**, таблицы/RLS, worker grants, import → fingerprint/lineage + **коррекции** (§ ниже).
6. **Приёмка PR #25:** `staging_acceptance.py`, tenant B, webhook IP.
7. **Ручной UI** 10–15 мин (базовый acceptance).
8. **Завершение:** дамп после окна, отчёт `var/${WINDOW_ID}/` (`baseline.json`, `migrate_timing.txt`, smoke batch id), остановка VPS по политике.

---

## Команды (не выполнять из CI)

### Бэкап БД до миграции

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  TS=$(date -u +%Y%m%dT%H%M%SZ)
  mkdir -p "var/backups"
  docker compose --env-file .env -f infra/docker-compose.prod.yml \
    -f infra/docker-compose.prod.ip.override.yml \
    exec -T postgres \
    pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --format=custom \
    > "var/backups/pre-0022-0023-${TS}.dump"
  ls -la "var/backups/pre-0022-0023-${TS}.dump"'
```

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
| CI main на выбранном SHA | success |
| Бэкап `pre-0022-0023-*` создан, размер > 0 | да |
| Текущая ревизия alembic | `20261107_0021` **или** известная предыдущая (зафиксировать в notes) |
| `.env` не в git, `chmod 600` | да |
| Нет планов `FLUSHDB` | да |

---

## Проверки **после** migrate (head `20261111_0023`)

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

### 8. PR #25

`staging_acceptance.py`, tenant B, webhook — [runbook-staging-acceptance.md](runbook-staging-acceptance.md).

---

## Критерии отката

| Ситуация | Действие |
| --- | --- |
| **Migrate не завершился** / api не стартует | Откат **кода** на SHA до pull; БД без изменений (если migrate не commit) — повтор после fix |
| **0022/0023 применены, продукт неверен** | **Не** `alembic downgrade`, если есть строки в `reconciliation_run`, provenance или **`source_correction_finding`** — сработает `downgrade_blocked` |
| **Откат схемы при пустых новых таблицах** | Только если **все** новые таблицы пусты: последовательный downgrade до `20261107_0021`; затем откат кода |
| **Данные в provenance / corrections / run** | **Только восстановление из бэкапа** `pre-0022-0023-*` — **не** полагаться на downgrade на боевых данных |
| Rate limit / 429 | `redis-cli DEL 'register:<ip>'` — точечно |
| Критический FAIL | Остановить приёмку; не трогать prod |

Зафиксировать в `var/${WINDOW_ID}/notes.md`: `backup_file`, `alembic_before`, `alembic_after`, `smoke_fingerprint`, `smoke_corrections`, `rollback: none|code_only|db_restore`.

---

## Чек-лист приёмки владельцем

- [ ] WINDOW_ID, SHA main, время начала/конца migrate.
- [ ] Бэкап до migrate — имя, размер.
- [ ] Alembic **`20261111_0023`** подтверждён.
- [ ] RLS/grants 0022+0023 — PASS.
- [ ] Smoke provenance — PASS.
- [ ] Smoke коррекций (duplicate + period_overlap) — PASS или skip с причиной.
- [ ] Логи без `import_provenance_failed` / `correction_scan_failed` на smoke.
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
