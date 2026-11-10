# Окно деплоя на стенд · PR #25 + миграция `20261110_0022` (FA-R03.3-min)

**Назначение:** плановое окно выката на VPS **уже слитых** изменений:

- [PR #25](https://github.com/zugrov/fin_pilot/pull/25) — rate limit за Caddy, compose override, `staging_acceptance.py` (squash → `c34328f…`).
- [PR #34](https://github.com/zugrov/fin_pilot/pull/34) — **FA-R03.3-min**: fingerprint, lineage, `reconciliation_run`, миграция **`20261110_0022`** (product squash → `0fc224d…`).

**Команды ниже — только для копирования. Агент/CI/автоматизация их не выполняет.**

**Базовые runbook:** [runbook-staging-window.md](runbook-staging-window.md), [runbook-staging-acceptance.md](runbook-staging-acceptance.md), [runbook-staging.md](runbook-staging.md).  
**Устаревший узкий файл** (только #25): [runbook-staging-window-pr25.md](runbook-staging-window-pr25.md) — заменён этим документом.

---

## Версии (git)

| Объект | SHA / ссылка |
| --- | --- |
| **main на момент подготовки runbook** | `91a2d55c24dce159b0777d901610c37bf9a8ba68` |
| Минимум для PR #25 (rate limit) | `c34328f1873c636c4c23f5eb1e545cdc774e585f` |
| Минимум для FA-R03.3-min + migration 0022 | `0fc224d5eb39355a0911e1fb61a9024eb6307a14` |
| **Рекомендуемый выкат** | **main** `91a2d55…` (включает docs; product-схема — с `0fc224d`) |

Перед окном на сервере: `git fetch && git checkout main && git pull`; `git rev-parse HEAD` ≥ `0fc224d` для миграции 0022.

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
- Hook provenance после commit импорта (код API; на стенде проверяется smoke-импортом).

**Вне этого окна:** `persist_reconciliation_run` из сверки, cron retention, FA-R03.4+, деплой без бэкапа.

---

## Предусловия

- [ ] Владелец назначил **WINDOW_ID** (например `pr25-0022-YYYYMMDD`).
- [ ] Плейсхолдеры: `SSH_ALIAS`, `APP_ROOT`, `LOCAL_PORT`, `REMOTE_PROXY_PORT`, `BASE_URL`.
- [ ] Тестовый магазин ЮKassa, `STAGING_PASSWORD`, туннель — как в базовом runbook.
- [ ] **Не** боевой магазин, **не** данные клиента / ТОПКОМ, **не** `--force` / `--admin` на проде.
- [ ] Зафиксирован **SHA до окна** (откат кода без отката БД).

---

## Порядок шагов (обязательная последовательность)

1. **До касания продакшн-данных:** снять **бэкап БД** (pg_dump или согласованный snapshot VPS).
2. **Обновление кода:** `git pull` → SHA ≥ `0fc224d`.
3. **Миграция:** один прогон `alembic upgrade head` из **migrate**-контейнера/job с `MIGRATION_DATABASE_URL` (не из app без согласования).
4. **Пересборка и перезапуск:** `docker compose … up -d --build api worker beat frontend proxy` (три override — см. базовый runbook).
5. **Smoke post-migrate:** health, revision alembic, таблицы/RLS, worker grants, тестовый import → fingerprint/lineage.
6. **Приёмка PR #25:** `staging_acceptance.py`, tenant B, webhook IP (§ ниже).
7. **Ручной UI** 10–15 мин (базовый acceptance).
8. **Завершение:** дамп после окна, отчёт `var/${WINDOW_ID}/`, остановка VPS по политике.

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
    > "var/backups/pre-0022-${TS}.dump"
  ls -la "var/backups/pre-0022-${TS}.dump"'
```

Плейсхолдеры `POSTGRES_*` — из `.env` на сервере (в протокол не копировать пароли).

### Обновление кода

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  git fetch origin
  git checkout main
  git pull
  git rev-parse HEAD'
```

### Миграция (пример: одноразовый migrate-контейнер)

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  docker compose --env-file .env \
    -f infra/docker-compose.prod.yml \
    -f infra/docker-compose.prod.ip.override.yml \
    run --rm migrate alembic upgrade head'
```

Ожидание: exit 0, в логе — `Running upgrade 20261107_0021 -> 20261110_0022`.

### Compose up после миграции

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  docker compose --env-file .env \
    -f infra/docker-compose.prod.yml \
    -f infra/docker-compose.prod.ip.override.yml \
    -f infra/docker-compose.prod.deploy.override.yml \
    up -d --build api worker beat frontend proxy'
```

### Health

```bash
ssh "${SSH_ALIAS}" 'curl -fsS http://127.0.0.1/health/live && echo && curl -fsS http://127.0.0.1/health/ready'
```

### Туннель и приёмка (локально)

```bash
ssh -N -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PROXY_PORT}" "${SSH_ALIAS}"

export STAGING_BASE_URL="http://127.0.0.1:${LOCAL_PORT}"
export STAGING_BILLING_MODE=checkout
python3 scripts/staging_acceptance.py
```

---

## Проверки **до** миграции

| Проверка | PASS |
| --- | --- |
| CI main на выбранном SHA | success (backend, frontend, playwright) |
| Бэкап `pre-0022-*` создан, размер > 0 | да |
| Текущая ревизия alembic | `20261107_0021` или известная предыдущая |
| `.env` не в git, `chmod 600` | да |
| Нет планов `FLUSHDB` | да |

---

## Проверки **после** миграции `20261110_0022`

Выполнять от имени **migrate/admin** (superuser или `MIGRATION_DATABASE_URL`), без клиентских выгрузок.

### 1. Версия Alembic

```sql
SELECT version_num FROM alembic_version;
```

Ожидание: `20261110_0022`.

### 2. Таблицы и объекты

```sql
SELECT to_regclass('public.import_source_fingerprints'),
       to_regclass('public.import_row_lineage'),
       to_regclass('public.reconciliation_run');
SELECT to_regprocedure('app_expire_reconciliation_runs(timestamptz, integer)');
```

Все не NULL / функция существует.

### 3. RLS и политики

```sql
SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
  AND c.relname IN (
    'import_source_fingerprints',
    'import_row_lineage',
    'reconciliation_run'
  );

SELECT tablename, policyname, roles::text, cmd
FROM pg_policies
WHERE tablename IN (
  'import_source_fingerprints',
  'import_row_lineage',
  'reconciliation_run'
)
ORDER BY tablename, policyname;
```

Ожидание: `relrowsecurity` и `relforcerowsecurity` = true; политики с `app_tenant()`; worker-политики на `reconciliation_run`.

### 4. Права ролей

```sql
SELECT grantee, privilege_type
FROM information_schema.role_table_grants
WHERE table_name = 'import_source_fingerprints'
  AND grantee IN ('finpilot_app', 'finpilot_worker');
```

Ожидание: app — SELECT, INSERT, UPDATE; worker — SELECT, INSERT (lineage/fingerprint по миграции 0022).

```sql
SELECT has_function_privilege(
  'finpilot_worker',
  'app_expire_reconciliation_runs(timestamptz, integer)',
  'EXECUTE'
);
```

Ожидание: `t`.

### 5. Smoke: импорт и provenance (синтетика)

Через UI/API стенда: компания **ООО «Топ»**, тестовый CSV cash (как в полигоне), upload → commit.

```sql
SELECT count(*) FROM import_source_fingerprints
WHERE tenant_id = :tenant_id;

SELECT count(*) FROM import_row_lineage l
JOIN raw_import_rows r ON r.id = l.raw_import_row_id
WHERE r.batch_id = :batch_id;
```

Ожидание: fingerprint ≥ 1, lineage ≥ 1 для проведённых строк.

### 6. Логи API/worker

```bash
ssh "${SSH_ALIAS}" 'cd "${APP_ROOT}" && docker compose --env-file .env \
  -f infra/docker-compose.prod.yml logs --since=30m api worker 2>&1 \
  | grep -E "import_provenance_failed|ERROR|Traceback" || true'
```

Ожидание: нет `import_provenance_failed` на успешном smoke; нет необъяснимых ERROR.

### 7. PR #25 (после smoke)

| Проверка | PASS |
| --- | --- |
| Register rate limit по реальному IP | ключ Redis `register:<client-ip>` |
| `staging_acceptance.py` | exit 0 |
| Tenant B isolation | 404 чужой dashboard |
| Webhook ЮKassa + XFF | 200, активация |

Детали — [runbook-staging-acceptance.md](runbook-staging-acceptance.md).

---

## Критерии отката

| Ситуация | Действие |
| --- | --- |
| **Миграция 0022 не применилась** / api не стартует | Откат **кода** на SHA до pull; БД без изменений — повторить после fix |
| **0022 применена, но продукт неверен** | **Не** `alembic downgrade`, если в `reconciliation_run` / provenance есть строки — сработает `downgrade_blocked` |
| **Нужен откат схемы 0022** (пустые новые таблицы) | Только если таблицы **пусты**: `alembic downgrade 20261107_0021` из migrate-контейнера; затем откат кода |
| **Данные в provenance/run** | **Только восстановление из бэкапа** `pre-0022-*` (point-in-time или полный restore) |
| Rate limit / 429 | `redis-cli DEL 'register:<ip>'` — точечно |
| Критический FAIL окна | Остановить приёмку; VPS для логов; не трогать prod |

Зафиксировать в `var/${WINDOW_ID}/notes.md`: `backup_file`, `alembic_before`, `alembic_after`, `smoke_fingerprint`, `rollback: none|code_only|db_restore`.

---

## Чек-лист приёмки владельцем

- [ ] WINDOW_ID, SHA, время начала/конца.
- [ ] Бэкап до миграции — имя файла, размер.
- [ ] Alembic `20261110_0022` подтверждён.
- [ ] RLS/grants — по § «Проверки после» (скрин/SQL без секретов).
- [ ] Smoke import → fingerprint + lineage — PASS.
- [ ] Логи без `import_provenance_failed` на smoke.
- [ ] PR #25: tenant B, webhook, acceptance script — PASS или обоснованный skip.
- [ ] STATE: **не** ставить `deployed`/`accepted` для 0022 без этой подписи.
- [ ] Решение: **PASS окна** / **FAIL** + план (code rollback / db restore).

После **PASS** владелец отдельным решением обновляет `STATE.json` (`migration_applied_staging`, deployed SHA).

---

## Критерии PASS / FAIL окна

**PASS** — все:

- SHA ≥ `0fc224d`, миграция 0022, health 200.
- Post-migrate SQL + smoke provenance — PASS.
- Acceptance script без критичных FAIL.
- Tenant B isolation PASS.
- Артефакты в `var/${WINDOW_ID}/`.

**FAIL** — любой критичный пункт выше + отсутствие бэкапа до migrate.

---

## Связанные записи

- STATE: `infra-staging-rate-limit`, `fa_r03_3_min`.
- Scope: [FA-R03.3-implementation-scope.md](roadmap/FA-R03.3-implementation-scope.md).
- Миграция: `backend/alembic/versions/20261110_0022_fa_r033_min_provenance.py`.
