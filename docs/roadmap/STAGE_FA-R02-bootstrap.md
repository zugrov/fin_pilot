# FA-R02 · Первые задачи (bootstrap после FA-R01)

Статус: **planned**. Реализация только после FA-R01 и разрешения на код/миграции.

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

**Риски.** Deadlock на unique file_hash + delivery insert; RLS на новой таблице.

## FA-R02.2 · Ревизии, entity id, unpost (минимум)

**Цель.** `source_entity_id` / revision order; строки unpost → review, не auto void.

**Границы.** Без snapshot tombstone policy (R02.4).

**Файлы.** `RawImportRow` или normalized payload, `dedup.py`, `*_import.py`, domain readers.

**Миграции.** Nullable columns on raw rows.

**Тесты.** changed/revise; stale revision rejected; unpost row не commit без review.

**Приёмка.** Существующие import tests pass; новые сценарии 6–8 из test-vectors.

**Риски.** Совместимость с `source_identities_key_uq`.

## FA-R02.3 · HTTP proposed ingest (отложено сразу после R02.1)

**Цель.** `POST …/ingestions` по OpenAPI proposed; machine token — stub до R11.

**Зависит от.** R02.1, R01.1 (firm context в UI не блокирует API).

## FA-R02.4 · Control totals и coverage states

**Цель.** DatasetCoverage; block commit on mismatch; не auto reconciled.

**Зависит от.** R02.1, решения владельца snapshot policy.
