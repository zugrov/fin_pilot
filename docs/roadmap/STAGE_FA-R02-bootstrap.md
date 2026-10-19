# FA-R02 · Первые задачи (bootstrap после FA-R01)

Статус: **in_progress** (этап FA-R02). **FA-R02.1**, **FA-R02.1b**, **FA-R02.2**, **FA-R02.3 accepted** 2026-10-19. **FA-R02.4** — **in_progress** (не accepted). FA-R01 accepted; deploy staging этим пакетом не входит.

**Snapshot vs deploy.** Принятый session transport product SHA — `ecb7d64c9ab91b3b0d9b1ab5d8bf057f3eea4f6c` (R02.3). Staging deployed baseline остаётся `7ee85e501735efcfa449ad8f44ef11258e5e4cf2`; session ingest, миграции **0011/0012/0013**, HTTP transaction boundary и R02.2 revision/unpost на staging **не** применены; `session_ingest_enabled` **не** включать.

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

**Handoff:** FA-R02.2 **accepted**; `current_task` → **FA-R02.3** (planned).

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

## FA-R02.2 · Ревизии, entity id, unpost (минимум)

**Статус:** **accepted** 2026-10-19.

**Product SHA:** `aedf0b8346d3416de5da8b87dc91d108abdb1468`.

**Цель (выполнено).** `source_entity_id` alias `external_id`; `source_revision` BIGINT (числовой порядок); `operation` upsert/unpost; commit-time gate; preview revision-конфликтов как review без CHECK/500; unpost → review без auto void/tombstone.

**Границы.** ClientBank legacy; **balances** — прежняя отдельная модель, регрессия сохранена; R02.3–R02.4 не входят.

**Миграция.** `20261019_0013`; runtime downgrade guard при watermark / non-legacy `operation`.

### FA-R02.2 · приёмка владельцем (2026-10-19)

**Revision и payload.**

- Legacy → versioned (same financial fields); missing revision после versioned (NULL `source_revision` + changed payload → 409 `revision_required`; same payload → skip).
- Equal revision / другой payload → preview review + 409 `revision_payload_conflict`.
- Higher revision / same payload → только watermark, без financial revision / без повторного `transaction_imported`.
- Stale после применённого watermark → preview `repeated`+review / commit 409 `stale_revision`.

**Commit-time gate и concurrency.**

- Старый preview после commit более новой revision; parallel first/existing identity; late-row batch rollback (amount, identity hash, watermark, `transaction_revisions`, audit, `preview_ready`).
- `identity_type_conflict`: preview invalid; commit 409 если слот другого типа появился после чистого preview.

**Unpost.**

- Explicit `operation=unpost` → review; без create/revise/void; applied watermark не продвигается; отсутствие финансовой строки не трактуется как отмена.

**Datasets.** Cash, revenue, plan, budget — versioned create/revise + watermark (parametrized integration).

**Workflows на aedf0b8:**

| Run | URL | Результат |
|-----|-----|-----------|
| CI [39249819030](https://github.com/zugrov/fin_pilot/actions/runs/39249819030) | backend **375 passed**, 0 failed/skipped; Ruff/Mypy ✓; frontend **89** unit + build ✓ |
| E2E [39249818954](https://github.com/zugrov/fin_pilot/actions/runs/39249818954) | **6 passed**, 0 failed/skipped |

**Локально (вне CI product SHA):** Ruff/Mypy/frontend/E2E FA-R01 — green; полный backend pytest — **2 failed**: `test_backup_restore` (restore service `:5433`); `test_year5_year6_upgrade_uses_paid_discount` (повтор фиксированного UUID `annual_offer_versions` из остатка локальной `finpilot_test`, не flake; fixture/TRUNCATE не менялись).

**Staging.** Deploy baseline **7ee85e5** без изменений; 0013 и R02.2 на стенде **не** заявлены.

**Оставшиеся ограничения (не блокируют приёмку R02.2).**

- Auto-void / tombstone / snapshot deletion при unpost — **не** реализованы.
- `identity_type_conflict` при upload, когда тип уже известен на preview — invalid + partial import (не HTTP 409).

**Handoff:** FA-R02.3 **accepted**; `current_task` → **FA-R02.4** (planned).

## FA-R02.3 · Session User Transport API

**Статус:** **accepted** 2026-10-19.

**Product SHA:** `ecb7d64c9ab91b3b0d9b1ab5d8bf057f3eea4f6c`.

**Scope (session-only).** Два маршрута: multipart **POST** ingest и **GET** актуального статуса delivery. Machine credentials, Bearer ingest, 1С — **FA-R11**, **не** реализованы этим пакетом. `json_records`, chunks, `client_package_id`, `control_totals` — **не** поддержаны.

**Реализовано (flag off по умолчанию).**

- `POST /api/v1/companies/{company_id}/ingestions`, `GET /api/v1/ingestions/{delivery_id}`.
- Auth: session + CSRF + company/connection/entitlement; Bearer → 401; `session_ingest_enabled=false` → 404.
- Envelope `1.0-session`, multipart (raw body ≤ 32 MiB, per-file limits), idempotency scope `session-ingest`, advisory lock same-key; replay **200** + сохранённое POST body; first **201**.
- Same-key concurrency ×20: один delivery/parts/batch/idempotency; partial/all-failed parts; **без** auto `commit_import`.
- Async multipart parse; sequential `run_in_threadpool` для actor/accept; одна `DbSession`; `get_db` commit-before-response (R02.1b); `/health/live` во время ожидания advisory lock.
- Multipart upload cleanup в проверенных сценариях (см. integration/unit tests).
- Контракт: `docs/roadmap/contracts/session-http-ingest.md`.

### FA-R02.3 · приёмка владельцем (2026-10-19)

**Workflows на ecb7d64 (attempt 1):**

| Run | URL | Результат |
|-----|-----|-----------|
| CI [39278467402](https://github.com/zugrov/fin_pilot/actions/runs/39278467402) | head `ecb7d64…`; **420 passed**, 0 failed/errors/skipped, 10 warnings; Ruff/Mypy ✓; frontend **89** unit + build ✓; Stop containers ✓ |
| E2E [39278467079](https://github.com/zugrov/fin_pilot/actions/runs/39278467079) | head `ecb7d64…`; **6 passed**, 0 failed/skipped; Stop containers ✓ |

**Локально (вне CI product SHA):** Ruff/Mypy/frontend/E2E FA-R01 — green на ecb7d64; полный backend pytest — **не** полностью зелёный: `test_backup_restore` (`pg_dump` `:5433`); `test_year5_year6_upgrade_uses_paid_discount` (billing UUID в локальной test DB).

**Staging.** Deploy baseline **7ee85e5** без изменений; новые пакеты/миграции на стенде **не** заявлены; флаг session ingest **не** включать.

**Оставшиеся ограничения (не блокируют приёмку R02.3).**

- Cancellation/disconnect multipart cleanup — отдельными тестами **не** подтверждён.
- `_files_to_close_on_error` — приватное поле установленного Starlette parser; **не** стабильный публичный контракт.
- R02.4 control totals / coverage — см. секцию FA-R02.4 ниже.

**Handoff:** FA-R02.4 **in_progress**.

**Зависит от.** R02.1, R02.2 (revision через те же bytes/readers).

## FA-R02.4 · Control totals и coverage states

**Статус:** **in_progress** (не accepted).

**Цель.** Отдельный validation layer; control totals по distinct `batch_id`; commit gates; `DatasetCoverage` claimed/reconciled; session `1.1-session`; owner reconcile endpoint.

**Не входит.** FA-R03/FA-R11; auto `reconciled` при matched; ClientBank `ДатаКонца` → `coverage_through`; deploy/flag.

**DDL.** `20261019_0014` — поля validation на `ingestion_deliveries`, таблица `dataset_coverage`.

**Зависит от.** R02.1–R02.3 (transport/session без переработки semantics 1.0).
