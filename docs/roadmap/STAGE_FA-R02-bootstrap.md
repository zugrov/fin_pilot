# FA-R02 · Первые задачи (bootstrap после FA-R01)

Статус: **in_progress** (этап). **FA-R02.1 accepted** 2026-10-19, product SHA `9fe5c06d8778b56556baa40932aa189c231696c1`. **FA-R02.2–R02.4** — planned. FA-R01 accepted; deploy staging этим пакетом не входит.

**Snapshot vs deploy.** Принятый код в репозитории — `9fe5c06…`. Staging deployed baseline остаётся `7ee85e501735efcfa449ad8f44ef11258e5e4cf2`; миграции 0011/0012 и wallet fix на staging **не** применены.

Опора: ADR-001-B, `contracts/*`.

## FA-R02.1 · Delivery + связь с batch

**Цель.** Материализовать проект `IngestionDelivery` и nullable `ImportBatch.delivery_id`;
UI file и почта создают delivery; transport idempotency по `delivery_key`.

**Границы.** Не менять алгоритмы `commit_import`; не включать API ingest (R02.3).

**Файлы (ожидаемо).**

- `backend/alembic/sql/00xx_ingestion_delivery.sql`, версия alembic
- `backend/app/models/imports.py`
- `backend/app/services/import_service.py` (`receive_import`)
- `backend/app/services/mail_service.py`
- тесты: `tests/integration/test_import_api.py`, новый `test_ingestion_delivery.py`

**API.** Внутренние вызовы; публичный proposed POST — ещё нет или feature flag.

**Миграции.** Аддитивные; backfill NULL; откат — drop FK, таблица optional.

**Тесты.** Повтор file → один batch; UI path создаёт delivery; email N parts → 1 delivery N batch.

**Приёмка.** CI green; фикстуры двух firm без изменения сумм.

### R02.1 (принятое решение, 2026-10-18)

- Материализованы `ingestion_deliveries`, `ingestion_delivery_parts`, nullable `import_batches.delivery_id` (только для **нового** batch), nullable `email_ingestions.delivery_id`.
- UI: `delivery_key = ui:{user_id}:{Idempotency-Key}`; HTTP idempotency до delivery; `delivery_id` в ответе upload — текущая доставка.
- Mail: delivery на `connection+UIDVALIDITY+UID`; fingerprint — manifest частей с полными SHA-256; повтор не меняет persisted `transport_complete` и preview-parts; `batch.delivery_id` только при создании batch.
- Downgrade 0011: guard при непустой `ingestion_deliveries`; balances guards не ослаблены.

**Риски.** Deadlock на unique file_hash + delivery insert; RLS на новой таблице.

**R02.1 fix (2026-10-19).** Конкурентный UI upload одного файла: `session.add(batch)` только внутри SAVEPOINT flush; `import_batches_file_uq` → dedup с ожиданием committed batch; regression `test_ui_concurrent_same_file_two_sessions` (+ stress ×20).

**R02.1 scope FK (2026-10-19).** Миграция `20261019_0012`: composite FK part→batch, batch→delivery, email→delivery; pre-check `upgrade_blocked` при scope mismatch; downgrade 0012→0011 восстанавливает слабые FK 0011.

**Wallet POST commit (2026-10-19).** `post_wallet`: `session.commit()` до HTTP success (FastAPI 0.143 / get_db commit после yield); regression `test_wallet_response_commit.py` (ASGI probe на `http.response.start`).

### FA-R02.1 · приёмка владельцем (2026-10-19)

**Product SHA:** `9fe5c06d8778b56556baa40932aa189c231696c1`.

**Delivery и parts:** file/mail адаптеры; message-level delivery; несколько вложений → parts; transport idempotency по `delivery_key`; persisted `transport_complete` / partial при повторе; legacy `batch.delivery_id = NULL`; первоначальная delivery batch; общий batch у разных delivery; без повторных финансовых записей.

**Конкурентность:** реальная гонка двух `Session`; stress ×20; один batch, два part, две delivery, два idempotency record, один `import_received` audit.

**DB scope:** миграции `20261018_0011`, `20261019_0012`; самостоятельные negative FK tests; RLS и downgrade safety; обязательные проверки без skipped.

**Wallet fix:** воспроизведение success-before-commit на предыдущем snapshot; commit до HTTP success в `post_wallet`; независимое чтение, replay/conflict, rollback при commit failure.

**Workflows на 9fe5c06:**

| Run | Результат |
|-----|-----------|
| CI 39212706594 | backend 328 passed, 0 skipped; frontend 89 unit + build; Ruff/Mypy green |
| E2E 39212706567 | attempt 1, 6 passed |

**Локально:** backend 328 passed + **1 failed** `test_backup_restore` (pg_dump `127.0.0.1:5433` refused) — локальный backend-прогон **не** полностью зелёный.

**Открытый риск (не закрыт):** общий `get_db` не менялся; гарантия commit-before-success доказана **только** для POST создания кошелька. Остальные write-endpoints требуют отдельного read-only аудита фактической границы commit/HTTP response и обработки commit failure до допуска к пилоту или расширению эксплуатации. Без аудита не утверждать, что каждый другой endpoint обязательно неисправен.

**Handoff:** `current_task` → FA-R02.2 (planned). Реализация R02.2 без отдельного разрешения не начинать.

### FA-R02.1b · HTTP transaction boundary · accepted 2026-10-19

**Product SHA:** `a78080a6c072ea851db9fa2d458cb0983af5a76a`.

- FastAPI **0.143.0**; `DbSession` = `Depends(get_db, scope="function")` на **96** `/api/v1` ops (**98** OpenAPI всего; `/health/live` без DB; `/health/ready` — отдельная Session).
- Один владелец request transaction — **`get_db`**; локальный commit в `post_wallet` **удалён**.
- YooKassa webhook: inbox до ack; duplicate-only 200 при `IntegrityError`.
- Regression: unit guard; ASGI probes (wallet, opening, tx, revenue, balances commit, webhook inbox, auth/me); commit-failure 5xx — см. `docs/roadmap/HTTP_TRANSACTION_BOUNDARY.md`.
- **CI** 39218808186: **341 passed**, 0 skipped; **E2E** 39218808291: **6 passed**.
- Product chain: `bacf02f` → `4f5eb72` → `f257b6f` → `6824a92` → `a78080a` (три последних — правки regression test setup/probe, не смена boundary).
- Staging **7ee85e5** — deploy этого пакета **не** выполнялся.
- Исторический риск commit-after-response **закрыт** для текущего HTTP graph; пилот-only готовность **не** утверждается.

**Handoff:** FA-R02.2 **in_progress** — revision/unpost на cash CSV/XLSX и revenue/plan/budget CSV; commit-time gate и advisory lock по `(tenant, company, namespace, external_id)`.

## FA-R02.2 · Ревизии, entity id, unpost (минимум)

**Статус:** in_progress (не accepted до green CI/E2E на product SHA).

**Цель.** `source_entity_id` alias `external_id`; `source_revision` BIGINT; `operation` upsert/unpost; stale/conflict на commit; unpost → review без auto void.

**Границы.** ClientBank legacy; balances только регрессия; без R02.3–R02.4.

**Миграция.** `20261019_0013` — аддитивные колонки, downgrade guard на watermark/non-legacy operation.

**Тесты.** `test_import_revision_unpost.py`, `test_revision_compare.py`, `test_import_meta.py`; полный import/regression suite.

**Риски.** `source_identities_key_uq` без изменений; entity_type conflict явный.

### FA-R02.2 · verification pass (2026-10-19, parent `85c39b1`, не accepted)

**Auth CI failure (диагностика).** `test_auth1_normalized_email_is_unique`: `count(users)==2` при ожидании 1. Воспроизведение: `tests/e2e/test_bootstrap.py` (seed `e2e-owner@example.com`) → integration auth1; до первого POST в БД уже **1** user, после двух register — **2**; `normalized_email` у auth-пары совпадает (`a.b+tag@example.com`). Причина: `clean_tables` делал TRUNCATE только **после** теста, не **до**; pytest collect — `tests/e2e` раньше `tests/integration`. Fix (tests-only): `truncate_integration_tables()` в setup/teardown + guard `users==0` в auth1.

**DB regression R02.2 (добавлено в `test_import_revision_unpost.py`).** Concurrent first/existing identity (2×Session, Barrier); late-row batch rollback (`revision_payload_conflict`); identity_type на preview; runtime downgrade 0013 с watermark; wiring watermark/legacy/repeat/conflict; parametrized cash/revenue/plan/budget create+revise.

**Ограничения / product gaps (не чинились в этом проходе).** Preview с `duplicate_status=review` (stale/revision_required/payload conflict при уже применённом watermark) **не** проходит CHECK `raw_import_rows_status_ck` — такие строки нельзя materialize в одном upload; stale/payload-conflict проверяются **разными batch** до/после commit (как `test_stale_revision_*`). `identity_type_conflict` на commit → **invalid row + partial import**, не HTTP 409. Legacy CSV без revision после versioned identity с **другим** payload на upload не доводится до commit (review/status ck); повтор versioned/legacy с тем же payload — skip без новой финансовой строки.

## FA-R02.3 · HTTP proposed ingest (отложено сразу после R02.1)

**Цель.** `POST …/ingestions` по OpenAPI proposed; machine token — stub до R11.

**Зависит от.** R02.1, R01.1 (firm context в UI не блокирует API).

## FA-R02.4 · Control totals и coverage states

**Цель.** DatasetCoverage; block commit on mismatch; не auto reconciled.

**Зависит от.** R02.1, решения владельца snapshot policy.
