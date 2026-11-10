# Чек-лист интеграционных тестов миграций

При добавлении новой ревизии Alembic:

1. **`HEAD_REVISION`** — единственный источник «текущей головы» в `backend/tests/integration/conftest.py`; assert «схема на head» только через него.
2. **Roundtrip** — отдельные константы пакета (`FA_R033_MIGRATION_REVISION`, `FA_R034_MIGRATION_REVISION`, …) для `upgrade`/`downgrade` конкретного шага, не дублировать строку head вручную в новых тестах.
3. **Downgrade guard** — тест с данными в таблицах новой миграции → `downgrade_blocked`; пустые таблицы → полный roundtrip до `STAGING_BASELINE_REVISION` при необходимости.
4. **RLS** — после upgrade: `relrowsecurity`, `relforcerowsecurity`, политики `app_tenant()` (отдельный тест или SQL в runbook).
5. **Grants** — `finpilot_app` / `finpilot_worker` на новые таблицы и функции retention (как в post-migrate SQL runbook).
6. **Пин схемы для legacy-сценариев** (0011/0012 и т.п.) — именованная константа «revision under test», не `HEAD_REVISION` и не строковый литерал без имени.

Локальная репетиция окна стенда: `scripts/rehearse_staging_migrations_0022_0023.py` (нужен Postgres, как в CI).
