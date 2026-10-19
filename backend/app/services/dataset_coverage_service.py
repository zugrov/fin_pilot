"""DatasetCoverage: claims и owner reconciliation (FA-R02.4)."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

from app.errors import AppError
from app.models.identity import AuditLog, Company, IdempotencyRecord, User
from app.models.imports import (
    DatasetCoverage,
    ImportBatch,
    IngestionDelivery,
    IngestionDeliveryPart,
    SourceConnection,
)
from app.security.access import OWNER
from app.security.tokens import canonical_hash
from app.services.control_totals_service import batches_rows_within_period
from app.services.delivery_validation_service import (
    BATCH_COMMITTED_OK,
    VALIDATION_MATCHED,
    delivery_batch_ids,
    refresh_delivery_validation,
)
from app.services.ingestion_delivery_service import PART_FAILED
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

STATE_CLAIMED = "claimed"
STATE_RECONCILED = "reconciled"
STATE_SUPERSEDED = "superseded"

VERIFIED_DATASETS = frozenset({"cash", "revenue"})
RECONCILE_SCOPE = "delivery-reconcile"
COVERAGE_SCOPE_LOCK_PREFIX = "dataset-coverage"


def coverage_scope_lock_key(connection: SourceConnection) -> str:
    return (
        f"{COVERAGE_SCOPE_LOCK_PREFIX}:{connection.tenant_id}:"
        f"{connection.id}:{connection.dataset}"
    )


def acquire_coverage_scope_lock(session: Session, connection: SourceConnection) -> None:
    """Сериализация coverage на scope connection+dataset.

    Порядок относительно commit_import:
    1. FOR UPDATE на import_batches (_locked_batch);
    2. pg_advisory_xact_lock на coverage scope (invalidate).
    reconcile берёт только coverage lock — циклического ожидания нет.
    """
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": coverage_scope_lock_key(connection)},
    )


def record_completeness_claim(
    session: Session,
    delivery: IngestionDelivery,
    connection: SourceConnection,
    company: Company,
    claim: dict[str, Any] | None,
    at: datetime,
) -> None:
    if not claim or connection.dataset not in VERIFIED_DATASETS:
        return
    if delivery.period_from is None or delivery.period_to is None:
        return
    delivery_id = delivery.id
    acquire_coverage_scope_lock(session, connection)
    session.expire(delivery)
    reloaded_delivery = session.get(IngestionDelivery, delivery_id)
    if reloaded_delivery is None:
        return
    delivery = reloaded_delivery
    period_from = delivery.period_from
    period_to = delivery.period_to
    if period_from is None or period_to is None:
        return
    existing = session.scalar(
        select(DatasetCoverage).where(
            DatasetCoverage.tenant_id == company.tenant_id,
            DatasetCoverage.delivery_id == delivery.id,
            DatasetCoverage.state == STATE_CLAIMED,
        )
    )
    if existing is not None:
        return
    row = DatasetCoverage(
        id=uuid.uuid4(),
        tenant_id=company.tenant_id,
        company_id=company.id,
        connection_id=connection.id,
        dataset=connection.dataset,
        period_start=period_from,
        period_end=period_to,
        period_timezone=delivery.period_timezone or company.timezone,
        version=_next_coverage_version(
            session,
            company.tenant_id,
            company.id,
            connection.id,
            connection.dataset,
            period_from,
            period_to,
            delivery.period_timezone or company.timezone,
        ),
        supersedes_id=None,
        state=STATE_CLAIMED,
        claim={"completeness_claim": claim, "delivery_id": str(delivery.id)},
        evidence={"source": "envelope"},
        delivery_id=delivery.id,
        reconciled_by=None,
        reconciled_at=None,
        reconciliation_basis=None,
        created_at=at,
        updated_at=at,
    )
    session.add(row)
    session.flush()


def invalidate_reconciled_for_connection(
    session: Session,
    connection: SourceConnection,
    at: datetime,
    *,
    reason: str,
) -> None:
    if connection.dataset not in VERIFIED_DATASETS:
        return
    connection_id = connection.id
    acquire_coverage_scope_lock(session, connection)
    session.expire(connection)
    reloaded_connection = session.get(SourceConnection, connection_id)
    if reloaded_connection is None:
        return
    connection = reloaded_connection
    rows = session.scalars(
        select(DatasetCoverage).where(
            DatasetCoverage.tenant_id == connection.tenant_id,
            DatasetCoverage.connection_id == connection.id,
            DatasetCoverage.dataset == connection.dataset,
            DatasetCoverage.state == STATE_RECONCILED,
        )
    ).all()
    for item in rows:
        item.state = STATE_SUPERSEDED
        evidence = dict(item.evidence)
        evidence["invalidated_at"] = at.isoformat()
        evidence["invalidation_reason"] = reason
        item.evidence = evidence
        item.updated_at = at
    session.flush()


def _coverage_scope(
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    connection_id: uuid.UUID,
    dataset: str,
    period_start: date,
    period_end: date,
    period_timezone: str,
):
    return (
        DatasetCoverage.tenant_id == tenant_id,
        DatasetCoverage.company_id == company_id,
        DatasetCoverage.connection_id == connection_id,
        DatasetCoverage.dataset == dataset,
        DatasetCoverage.period_start == period_start,
        DatasetCoverage.period_end == period_end,
        DatasetCoverage.period_timezone == period_timezone,
    )


def _next_coverage_version(
    session: Session,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    connection_id: uuid.UUID,
    dataset: str,
    period_start: date,
    period_end: date,
    period_timezone: str,
) -> int:
    filters = _coverage_scope(
        tenant_id, company_id, connection_id, dataset, period_start, period_end, period_timezone
    )
    current = session.scalar(
        select(func.max(DatasetCoverage.version)).where(*filters)
    )
    return 1 if current is None else int(current) + 1


def _has_completeness_claim(session: Session, delivery: IngestionDelivery) -> bool:
    if not delivery.completeness_claim:
        return False
    row = session.scalar(
        select(DatasetCoverage).where(
            DatasetCoverage.tenant_id == delivery.tenant_id,
            DatasetCoverage.delivery_id == delivery.id,
            DatasetCoverage.state == STATE_CLAIMED,
        )
    )
    return row is not None


def _all_delivery_batches_committed(session: Session, delivery_id: uuid.UUID) -> bool:
    parts = session.scalars(
        select(IngestionDeliveryPart).where(IngestionDeliveryPart.delivery_id == delivery_id)
    ).all()
    for part in parts:
        if part.part_status == PART_FAILED or part.batch_id is None:
            return False
        batch = session.get(ImportBatch, part.batch_id)
        if batch is None or batch.status not in BATCH_COMMITTED_OK:
            return False
        if batch.quality_flags:
            return False
    return True


def _delivery_superseded_after_import(session: Session, delivery: IngestionDelivery) -> bool:
    rows = session.scalars(
        select(DatasetCoverage).where(
            DatasetCoverage.tenant_id == delivery.tenant_id,
            DatasetCoverage.delivery_id == delivery.id,
            DatasetCoverage.state == STATE_SUPERSEDED,
        )
    ).all()
    return any(item.evidence.get("invalidation_reason") == "import_commit" for item in rows)


def _connection_changed_after_delivery(
    session: Session,
    connection: SourceConnection,
    delivery: IngestionDelivery,
) -> bool:
    batch_ids = delivery_batch_ids(session, delivery.id)
    if not batch_ids:
        return False
    completed_at = session.scalar(
        select(func.max(ImportBatch.completed_at)).where(
            ImportBatch.id.in_(batch_ids),
            ImportBatch.status.in_(tuple(BATCH_COMMITTED_OK | {"completed_with_errors"})),
        )
    )
    if completed_at is None:
        return False
    later = session.scalar(
        select(ImportBatch.id).where(
            ImportBatch.tenant_id == connection.tenant_id,
            ImportBatch.connection_id == connection.id,
            ImportBatch.id.notin_(batch_ids),
            ImportBatch.status.in_(tuple(BATCH_COMMITTED_OK | {"completed_with_errors"})),
            ImportBatch.completed_at.isnot(None),
            ImportBatch.completed_at > completed_at,
        )
    )
    return later is not None


def _batch_evidence(session: Session, batch_ids: list[uuid.UUID]) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    for batch_id in batch_ids:
        batch = session.get(ImportBatch, batch_id)
        if batch is None:
            continue
        evidence.append(
            {
                "batch_id": str(batch.id),
                "file_hash": batch.file_hash,
                "rows_committed": str(batch.rows_committed),
                "status": batch.status,
            }
        )
    return evidence


def _reconcile_request_hash(
    delivery: IngestionDelivery,
    reconciliation_basis: str,
    calculated: dict[str, Any] | None,
) -> str:
    payload = json.dumps(
        {
            "delivery_id": str(delivery.id),
            "basis": reconciliation_basis.strip(),
            "fingerprint": delivery.request_fingerprint,
            "validation": delivery.validation_status,
            "calculated": calculated,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return canonical_hash(payload)


def _idempotent_reconcile(
    session: Session, user: User, key: str, request_hash: str
) -> IdempotencyRecord | None:
    row = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.scope == RECONCILE_SCOPE,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if row is None:
        return None
    if row.request_hash != request_hash:
        raise AppError(409, "idempotency_conflict", "Другие параметры для того же ключа сверки")
    return row


def _remember_reconcile(
    session: Session,
    user: User,
    tenant_id: uuid.UUID,
    key: str,
    request_hash: str,
    body: dict[str, Any],
    at: datetime,
) -> None:
    session.add(
        IdempotencyRecord(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user.id,
            scope=RECONCILE_SCOPE,
            idempotency_key=key,
            request_hash=request_hash,
            status_code=200,
            response_body=body,
            created_at=at,
        )
    )
    session.flush()


def reconcile_delivery(
    session: Session,
    delivery: IngestionDelivery,
    connection: SourceConnection,
    company: Company,
    user: User,
    membership,
    *,
    reconciliation_basis: str,
    idempotency_key: str,
    at: datetime,
) -> dict[str, Any]:
    if membership.role != OWNER:
        raise AppError(403, "forbidden", "Сверку может подтвердить только owner")
    if connection.dataset not in VERIFIED_DATASETS:
        raise AppError(422, "validation_error", "Сверка покрытия недоступна для dataset")
    if not reconciliation_basis.strip():
        raise AppError(422, "validation_error", "Нужно основание сверки")
    if delivery.period_from is None or delivery.period_to is None:
        raise AppError(409, "conflict", "У delivery не задан период")
    if not _has_completeness_claim(session, delivery):
        raise AppError(409, "conflict", "Нет completeness claim для delivery")

    delivery_id = delivery.id
    connection_id = connection.id
    company_id = company.id
    acquire_coverage_scope_lock(session, connection)
    session.expire(delivery)
    session.expire(connection)
    session.expire(company)
    reloaded_delivery = session.get(IngestionDelivery, delivery_id)
    reloaded_connection = session.get(SourceConnection, connection_id)
    reloaded_company = session.get(Company, company_id)
    if reloaded_delivery is None or reloaded_connection is None or reloaded_company is None:
        raise AppError(409, "conflict", "Delivery или источник недоступны")
    delivery = reloaded_delivery
    connection = reloaded_connection
    company = reloaded_company
    period_from = delivery.period_from
    period_to = delivery.period_to
    if period_from is None or period_to is None:
        raise AppError(409, "conflict", "У delivery не задан период")

    refresh_delivery_validation(session, delivery, connection, at)
    request_hash = _reconcile_request_hash(
        delivery, reconciliation_basis, delivery.control_totals_calculated
    )
    replay = _idempotent_reconcile(session, user, idempotency_key, request_hash)
    if replay is not None:
        return dict(replay.response_body)

    if delivery.validation_status != VALIDATION_MATCHED:
        raise AppError(409, "conflict", "Control totals должны быть matched")
    if not _all_delivery_batches_committed(session, delivery.id):
        raise AppError(409, "conflict", "Не все batches delivery проведены успешно")
    if _delivery_superseded_after_import(session, delivery):
        raise AppError(409, "coverage_stale", "Delivery устарела после изменяющего импорта")
    if _connection_changed_after_delivery(session, connection, delivery):
        raise AppError(409, "coverage_stale", "Появились более новые импорты источника")

    batch_ids = delivery_batch_ids(session, delivery.id)
    period_tz = delivery.period_timezone or company.timezone
    if not batches_rows_within_period(
        session,
        batch_ids,
        connection.dataset,
        period_from,
        period_to,
    ):
        raise AppError(409, "conflict", "Даты данных не входят в заявленный период")

    prior_reconciled = session.scalars(
        select(DatasetCoverage)
        .where(
            *_coverage_scope(
                company.tenant_id,
                company.id,
                connection.id,
                connection.dataset,
                period_from,
                period_to,
                period_tz,
            ),
            DatasetCoverage.state == STATE_RECONCILED,
        )
        .order_by(DatasetCoverage.version.desc())
        .limit(1)
    ).first()
    version = _next_coverage_version(
        session,
        company.tenant_id,
        company.id,
        connection.id,
        connection.dataset,
        period_from,
        period_to,
        period_tz,
    )
    supersedes = None if prior_reconciled is None else prior_reconciled.id
    if prior_reconciled is not None:
        prior_reconciled.state = STATE_SUPERSEDED
        prior_reconciled.updated_at = at

    evidence = {
        "delivery_id": str(delivery.id),
        "batch_ids": [str(i) for i in batch_ids],
        "batch_evidence": _batch_evidence(session, batch_ids),
        "validation_status": delivery.validation_status,
        "calculated_totals": delivery.control_totals_calculated,
        "period_timezone": period_tz,
        "idempotency_key": idempotency_key,
        "request_fingerprint": delivery.request_fingerprint,
    }
    row = DatasetCoverage(
        id=uuid.uuid4(),
        tenant_id=company.tenant_id,
        company_id=company.id,
        connection_id=connection.id,
        dataset=connection.dataset,
        period_start=period_from,
        period_end=period_to,
        period_timezone=period_tz,
        version=version,
        supersedes_id=supersedes,
        state=STATE_RECONCILED,
        claim={
            "control_totals": dict(delivery.control_totals_claim or {}),
            "completeness_claim": dict(delivery.completeness_claim or {}),
        },
        evidence=evidence,
        delivery_id=delivery.id,
        reconciled_by=user.id,
        reconciled_at=at,
        reconciliation_basis=reconciliation_basis.strip(),
        created_at=at,
        updated_at=at,
    )
    session.add(row)
    session.flush()
    session.add(
        AuditLog(
            tenant_id=company.tenant_id,
            user_id=user.id,
            action="delivery_coverage_reconciled",
            entity_type="dataset_coverage",
            entity_id=row.id,
            before_redacted=None,
            after_redacted={"delivery_id": str(delivery.id), "version": version},
            request_id=None,
            created_at=at,
        )
    )
    session.flush()
    body = _coverage_payload(row)
    _remember_reconcile(
        session, user, company.tenant_id, idempotency_key, request_hash, body, at
    )
    return body


def effective_reconciled_coverage(
    session: Session,
    connection: SourceConnection,
    period_start: date,
    period_end: date,
    period_timezone: str,
) -> DatasetCoverage | None:
    return session.scalar(
        select(DatasetCoverage)
        .where(
            *_coverage_scope(
                connection.tenant_id,
                connection.company_id,
                connection.id,
                connection.dataset,
                period_start,
                period_end,
                period_timezone,
            ),
            DatasetCoverage.state == STATE_RECONCILED,
        )
        .order_by(DatasetCoverage.version.desc())
    )


def _coverage_payload(row: DatasetCoverage) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "state": row.state,
        "dataset": row.dataset,
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "period_timezone": row.period_timezone,
        "version": row.version,
        "delivery_id": None if row.delivery_id is None else str(row.delivery_id),
        "reconciled_at": None if row.reconciled_at is None else row.reconciled_at.isoformat(),
        "legacy_coverage_through_hint": None,
    }


def legacy_revenue_coverage_claim(
    session: Session,
    connection: SourceConnection,
    coverage_through: date,
    at: datetime,
    *,
    timezone: str = "Europe/Moscow",
) -> None:
    """POST coverage — legacy claim, не reconciled."""
    connection_id = connection.id
    acquire_coverage_scope_lock(session, connection)
    session.expire(connection)
    reloaded_connection = session.get(SourceConnection, connection_id)
    if reloaded_connection is None:
        return
    connection = reloaded_connection
    row = DatasetCoverage(
        id=uuid.uuid4(),
        tenant_id=connection.tenant_id,
        company_id=connection.company_id,
        connection_id=connection.id,
        dataset=connection.dataset,
        period_start=coverage_through,
        period_end=coverage_through,
        period_timezone=timezone,
        version=_next_coverage_version(
            session,
            connection.tenant_id,
            connection.company_id,
            connection.id,
            connection.dataset,
            coverage_through,
            coverage_through,
            timezone,
        ),
        supersedes_id=None,
        state=STATE_CLAIMED,
        claim={"legacy_api": "POST /coverage", "coverage_through": coverage_through.isoformat()},
        evidence={"source": "legacy_hint"},
        delivery_id=None,
        reconciled_by=None,
        reconciled_at=None,
        reconciliation_basis=None,
        created_at=at,
        updated_at=at,
    )
    session.add(row)
    session.flush()
