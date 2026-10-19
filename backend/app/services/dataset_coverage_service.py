"""DatasetCoverage: claims и owner reconciliation (FA-R02.4)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from app.errors import AppError
from app.models.identity import Company, User
from app.models.imports import (
    DatasetCoverage,
    ImportBatch,
    IngestionDelivery,
    IngestionDeliveryPart,
    SourceConnection,
)
from app.security.access import OWNER
from app.services.delivery_validation_service import (
    VALIDATION_MATCHED,
    delivery_batch_ids,
    refresh_delivery_validation,
)
from app.services.ingestion_delivery_service import PART_PREVIEW
from sqlalchemy import select
from sqlalchemy.orm import Session

STATE_CLAIMED = "claimed"
STATE_RECONCILED = "reconciled"
STATE_SUPERSEDED = "superseded"

VERIFIED_DATASETS = frozenset({"cash", "revenue"})


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
        period_start=delivery.period_from,
        period_end=delivery.period_to,
        period_timezone=delivery.period_timezone or company.timezone,
        version=1,
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


def _all_delivery_batches_committed(session: Session, delivery_id: uuid.UUID) -> bool:
    parts = session.scalars(
        select(IngestionDeliveryPart).where(IngestionDeliveryPart.delivery_id == delivery_id)
    ).all()
    for part in parts:
        if part.part_status != PART_PREVIEW or part.batch_id is None:
            return False
        batch = session.get(ImportBatch, part.batch_id)
        if batch is None or batch.status not in {"completed", "completed_with_errors"}:
            return False
        if batch.status == "completed_with_errors":
            return False
        if batch.quality_flags:
            return False
    return True


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
    refresh_delivery_validation(session, delivery, connection, at)
    if delivery.validation_status != VALIDATION_MATCHED:
        raise AppError(409, "conflict", "Control totals должны быть matched")
    if not _all_delivery_batches_committed(session, delivery.id):
        raise AppError(409, "conflict", "Не все batches delivery проведены успешно")

    existing = session.scalar(
        select(DatasetCoverage).where(
            DatasetCoverage.tenant_id == delivery.tenant_id,
            DatasetCoverage.delivery_id == delivery.id,
            DatasetCoverage.state == STATE_RECONCILED,
        )
    )
    if existing is not None and existing.evidence.get("idempotency_key") == idempotency_key:
        return _coverage_payload(existing)

    prior = session.scalar(
        select(DatasetCoverage)
        .where(
            DatasetCoverage.tenant_id == delivery.tenant_id,
            DatasetCoverage.connection_id == connection.id,
            DatasetCoverage.dataset == connection.dataset,
            DatasetCoverage.state == STATE_RECONCILED,
        )
        .order_by(DatasetCoverage.version.desc())
    )
    version = 1 if prior is None else prior.version + 1
    supersedes = None if prior is None else prior.id
    if prior is not None:
        prior.state = STATE_SUPERSEDED
        prior.updated_at = at

    evidence = {
        "delivery_id": str(delivery.id),
        "batch_ids": [str(i) for i in delivery_batch_ids(session, delivery.id)],
        "validation_status": delivery.validation_status,
        "calculated_totals": delivery.control_totals_calculated,
        "period_timezone": delivery.period_timezone or company.timezone,
        "idempotency_key": idempotency_key,
    }
    row = DatasetCoverage(
        id=uuid.uuid4(),
        tenant_id=company.tenant_id,
        company_id=company.id,
        connection_id=connection.id,
        dataset=connection.dataset,
        period_start=delivery.period_from,
        period_end=delivery.period_to,
        period_timezone=delivery.period_timezone or company.timezone,
        version=version,
        supersedes_id=supersedes,
        state=STATE_RECONCILED,
        claim=dict(delivery.control_totals_claim or {}),
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
    return _coverage_payload(row)


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
    row = DatasetCoverage(
        id=uuid.uuid4(),
        tenant_id=connection.tenant_id,
        company_id=connection.company_id,
        connection_id=connection.id,
        dataset=connection.dataset,
        period_start=coverage_through,
        period_end=coverage_through,
        period_timezone=timezone,
        version=1,
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
