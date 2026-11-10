# FA-R03.2 · план подключения `persist_reconciliation_run` (после окна migrate 0023)

**Статус:** plan-only, **без кода в main до окна стенда**.  
**Решение владельца 2026-11-10:** запись `reconciliation_run` на стенде — **после** окна с `alembic head = 20261111_0023`.

---

## Контекст

- Сервис уже в репозитории: `backend/app/services/reconciliation_run_service.py` (`persist_reconciliation_run`, `assert_can_persist_run`).
- Таблица `reconciliation_run` создаётся миграцией `20261110_0022`; до окна на **staging** таблицы нет.
- Read-only сверка bank↔card51 сегодня: API `GET /companies/{id}/reconciliation/bank-card-51` + `bank_card_reconciliation_service.report_for_company_local` — **без записи в БД**.
- CLI `python -m app.tools.fa_r03_check` — вне CI, только локальные/var образцы.

---

## Точка вызова (целевая)

| Контур | Где | Когда вызывать persist |
| --- | --- | --- |
| **Product (после окна)** | После успешного завершения расчёта сверки bank↔card51 в **письме в БД** (не read-only local-only API) | Когда включён флаг и пользователь имеет finance-write + verified email |
| **CLI (опционально)** | `fa_r03_check` при флаге `--persist-run` | Только dev/staging с migrate 0022+; не в CI по умолчанию |

**Не в v1 плана:** запись из read-only HTTP `GET …/reconciliation/bank-card-51` (сохраняем семантику «осмотр без побочных эффектов»).

Предлагаемая цепочка (product path, будущий PR):

1. Загрузка/выбор периода и входов (fingerprints/hashes из provenance или batch metadata — без сырых PII в JSON).
2. Вызов доменной сверки (как сейчас в `match_bank_to_card51` / отчёт).
3. При `metrics` «passed» или «completed_with_warnings» — **опционально** `persist_reconciliation_run` в той же DB-транзакции, что и audit, **после** commit бизнес-чтения (append-only insert).

---

## Входные данные `persist_reconciliation_run`

Из design FA-R03.3 и сигнатуры сервиса:

- `tenant_id`, `company_id`, `user` (verified, finance-write).
- `run_kind`: **`bank_card_51`** (единственный CHECK в DDL).
- `period_year`, `period_month`.
- `input_fingerprints`, `input_hashes` — JSON без полей из `_FORBIDDEN_JSON_KEYS` (scrub в сервисе).
- `metrics`, `group_refs` — агрегаты сверки (счётчики, суммы, ссылки на группы — без назначений платежей).
- `engine_version` — версия пакета matching/reconcile.
- `supersedes_run_id` — optional, при повторном прогоне за период (политика v1: новая строка, без UPDATE).

---

## Поведение при ошибке

| Ситуация | Поведение |
| --- | --- |
| Ошибка **до** persist (парсинг, 404 local samples) | Как сейчас — `AppError`/503, **без** insert |
| Ошибка **при** insert (RLS, constraint) | Логировать `reconciliation_run_persist_failed`; **не** откатывать уже показанный read-only отчёт, если persist в отдельной транзакции; если в одной TX с отчётом — откат только persist-пути |
| Нет прав / email unverified | `assert_can_persist_run` → 403, отчёт read-only доступен |

Принцип: **persist не ломает основной путь просмотра сверки**.

---

## Флаги включения (staging)

Предлагаемые имена (реализация в отдельном PR):

| Переменная | Default | Staging после окна |
| --- | --- | --- |
| `RECONCILIATION_RUN_PERSIST_ENABLED` | `false` | `true` только после smoke 0023 + решение владельца |
| `FA_R03_LOCAL_RECONCILIATION_*` | как сейчас | без изменения read-only local API |

Не смешивать с `SEND_*` / billing / migrate.

---

## Тесты (будущий кодовый PR)

1. Integration: при flag on — insert в `reconciliation_run`, RLS tenant isolation (как `test_fa_r033_provenance_rls`).
2. Unit: scrub JSON, `assert_can_persist_run` (operator forbidden).
3. Негатив: downgrade guard не затрагивается, если persist не вызывался на downgrade.
4. **Не** грузить клиентские sample в git.

---

## Критерий приёмки после окна

- [ ] Staging: `alembic_version = 20261111_0023`.
- [ ] Флаг persist включён только на staging.
- [ ] Один smoke-прогон сверки (синтетика «Топ») создаёт **ровно одну** строку `reconciliation_run` с `run_kind = bank_card_51`.
- [ ] Повторный прогон — вторая строка (append-only), без UPDATE legacy cash/revenue.
- [ ] Оператор без finance-write — 403, строк в БД нет.
- [ ] В `var/${WINDOW_ID}/notes.md` — id прогона, без PII.

---

## Связанные документы

- [FA-R03.3-provenance-design.md](FA-R03.3-provenance-design.md)
- [FA-R03.2-readiness.md](FA-R03.2-readiness.md)
- [runbook-staging-window-pr25-0022-0023.md](../runbook-staging-window-pr25-0022-0023.md)
