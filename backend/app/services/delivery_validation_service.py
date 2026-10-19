"""Validation слой delivery: control totals и snapshot gates (FA-R02.4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.errors import AppError
from app.models.imports import (
    ImportBatch,
    IngestionDelivery,
    IngestionDeliveryPart,
    SourceConnection,
)
from app.services.control_totals_service import (
    aggregate_delivery_totals,
    compare_totals,
    validate_claim_fields,
)
from app.services.ingestion_delivery_service import PART_FAILED, PART_PREVIEW
from sqlalchemy import select
from sqlalchemy.orm import Session

VALIDATION_NOT_CHECKED = "not_checked"
VALIDATION_MATCHED = "matched"
VALIDATION_MISMATCH = "mismatch"
VALIDATION_NOT_VERIFIABLE = "not_verifiable"


def delivery_batch_ids(session: Session, delivery_id: uuid.UUID) -> list[uuid.UUID]:
    parts = session.scalars(
        select(IngestionDeliveryPart).where(IngestionDeliveryPart.delivery_id == delivery_id)
    ).all()
    ids: list[uuid.UUID] = []
    for part in parts:
        if part.batch_id is not None:
            ids.append(part.batch_id)
    return ids


def refresh_delivery_validation(
    session: Session,
    delivery: IngestionDelivery,
    connection: SourceConnection,
    at: datetime,
) -> None:
    batch_ids = delivery_batch_ids(session, delivery.id)
    calculated, verifiable = aggregate_delivery_totals(session, batch_ids, connection)
    delivery.control_totals_calculated = calculated
    reasons: list[str] = []
    claim = delivery.control_totals_claim
    if claim:
        try:
            validate_claim_fields(claim, connection.dataset)
        except AppError:
            delivery.validation_status = VALIDATION_NOT_VERIFIABLE
            delivery.validation_block_reasons = ["claim_invalid"]
            delivery.updated_at = at
            session.flush()
            return
        if not verifiable or calculated is None:
            delivery.validation_status = VALIDATION_NOT_VERIFIABLE
            reasons.append("totals_not_verifiable")
        elif compare_totals(claim, calculated, connection.dataset):
            delivery.validation_status = VALIDATION_MATCHED
        else:
            delivery.validation_status = VALIDATION_MISMATCH
            reasons.append("control_totals_mismatch")
    else:
        delivery.validation_status = VALIDATION_NOT_CHECKED
    if delivery.ingest_mode == "snapshot":
        parts = session.scalars(
            select(IngestionDeliveryPart).where(
                IngestionDeliveryPart.delivery_id == delivery.id
            )
        ).all()
        if any(item.part_status == PART_FAILED for item in parts):
            reasons.append("snapshot_part_failed")
        if any(item.part_status != PART_PREVIEW or item.batch_id is None for item in parts):
            reasons.append("snapshot_incomplete")
        if claim and delivery.validation_status != VALIDATION_MATCHED:
            reasons.append("snapshot_totals_not_matched")
    delivery.validation_block_reasons = reasons
    delivery.updated_at = at
    session.flush()


def assert_batch_linked_to_delivery(
    session: Session,
    delivery: IngestionDelivery,
    batch: ImportBatch,
) -> None:
    part = session.scalar(
        select(IngestionDeliveryPart).where(
            IngestionDeliveryPart.delivery_id == delivery.id,
            IngestionDeliveryPart.batch_id == batch.id,
            IngestionDeliveryPart.tenant_id == delivery.tenant_id,
        )
    )
    if part is None:
        raise AppError(409, "forbidden", "Партия не связана с указанной delivery")


def resolve_commit_delivery_context(
    session: Session,
    batch: ImportBatch,
    delivery_id: uuid.UUID | None,
) -> IngestionDelivery | None:
    if delivery_id is not None:
        delivery = session.get(IngestionDelivery, delivery_id)
        if delivery is None or delivery.tenant_id != batch.tenant_id:
            raise AppError(404, "not_found", "Доставка не найдена")
        if delivery.company_id != batch.company_id or delivery.connection_id != batch.connection_id:
            raise AppError(409, "forbidden", "Delivery не совпадает с партией")
        assert_batch_linked_to_delivery(session, delivery, batch)
        return delivery
    if batch.delivery_id is None:
        return None
    return session.get(IngestionDelivery, batch.delivery_id)


def assert_commit_allowed(
    session: Session,
    delivery: IngestionDelivery | None,
    batch: ImportBatch,
    connection: SourceConnection,
) -> None:
    if delivery is None:
        return
    if delivery.id != batch.delivery_id and batch.delivery_id is not None:
        assert_batch_linked_to_delivery(session, delivery, batch)
    refresh_delivery_validation(session, delivery, connection, batch.created_at)
    if delivery.control_totals_claim:
        parts = session.scalars(
            select(IngestionDeliveryPart).where(
                IngestionDeliveryPart.delivery_id == delivery.id
            )
        ).all()
        if any(item.part_status == PART_FAILED for item in parts):
            raise AppError(409, "delivery_incomplete", "Delivery: есть failed parts")
        if any(item.batch_id is None or item.part_status != PART_PREVIEW for item in parts):
            raise AppError(409, "delivery_incomplete", "Delivery: не все parts готовы")
    if delivery.validation_status == VALIDATION_MISMATCH:
        raise AppError(409, "control_totals_mismatch", "Control totals не совпадают")
    if delivery.validation_status == VALIDATION_NOT_VERIFIABLE and delivery.control_totals_claim:
        raise AppError(
            409,
            "control_totals_unverifiable",
            "Невозможно проверить заявленные control totals",
        )
    if delivery.ingest_mode == "snapshot":
        parts = session.scalars(
            select(IngestionDeliveryPart).where(
                IngestionDeliveryPart.delivery_id == delivery.id
            )
        ).all()
        if any(item.part_status == PART_FAILED for item in parts):
            raise AppError(409, "delivery_incomplete", "Snapshot: есть failed parts")
        for part in parts:
            if part.batch_id is None or part.part_status != PART_PREVIEW:
                raise AppError(409, "delivery_incomplete", "Snapshot: не все parts готовы")
            linked = session.get(ImportBatch, part.batch_id)
            if linked is None or linked.status != "preview_ready":
                raise AppError(409, "delivery_incomplete", "Snapshot: batch не в preview_ready")
            rows_bad = any(
                row.duplicate_status == "invalid" or row.proposed_action == "review"
                for row in _batch_rows(session, linked)
            )
            if rows_bad:
                raise AppError(409, "delivery_incomplete", "Snapshot: invalid/review rows")
        if delivery.control_totals_claim and delivery.validation_status != VALIDATION_MATCHED:
            raise AppError(409, "delivery_incomplete", "Snapshot: totals не matched")
    if delivery.control_totals_claim and delivery.validation_status == VALIDATION_MISMATCH:
        raise AppError(409, "control_totals_mismatch", "Control totals не совпадают")


def _batch_rows(session: Session, batch: ImportBatch):
    from app.models.imports import RawImportRow

    return session.scalars(
        select(RawImportRow).where(RawImportRow.batch_id == batch.id)
    ).all()


def delivery_financial_summary(session: Session, delivery_id: uuid.UUID) -> dict[str, Any]:
    parts = session.scalars(
        select(IngestionDeliveryPart).where(IngestionDeliveryPart.delivery_id == delivery_id)
    ).all()
    batches: dict[str, str] = {}
    for part in parts:
        if part.batch_id is None:
            continue
        batch = session.get(ImportBatch, part.batch_id)
        if batch is not None:
            batches[str(part.batch_id)] = batch.status
    return {"batches": batches}
