"""FA-R03.4 v1: коррекции и коллизии источников после commit cash."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from app.domain.cash.unclassified import is_internal_transfer
from app.domain.imports.fa_r03.deposit_heuristics import is_deposit_like_cash_description
from app.domain.money import money
from app.models.cash import CashTransaction, TransferGroup
from app.models.imports import ImportBatch, RawImportRow, SourceConnection
from app.models.provenance import (
    ImportRowLineage,
    ImportSourceFingerprint,
    SourceCorrectionFinding,
)
from app.services.provenance_service import LineageEvent
from sqlalchemy import func, select
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class CashBatchPeriod:
    period_from: date | None
    period_to: date | None


def cash_period_from_lineage(
    session: Session, lineage_events: list[LineageEvent]
) -> CashBatchPeriod:
    tx_ids = [
        event.entity_id
        for event in lineage_events
        if event.entity_kind == "cash_transaction"
    ]
    if not tx_ids:
        return CashBatchPeriod(None, None)
    row = session.execute(
        select(
            func.min(CashTransaction.business_date),
            func.max(CashTransaction.business_date),
        ).where(CashTransaction.id.in_(tx_ids))
    ).one()
    return CashBatchPeriod(row[0], row[1])


def _normalize_doc_number(value: str | None) -> str:
    if not value:
        return ""
    return value.strip()


def _uuid_list(values: list[uuid.UUID]) -> list[str]:
    return [str(item) for item in values]


def _add_finding(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    batch_id: uuid.UUID,
    kind: str,
    fingerprint_ids: list[uuid.UUID],
    lineage_ids: list[uuid.UUID],
    period_from: date | None,
    period_to: date | None,
    details: dict,
    at: datetime,
    severity: str = "warning",
) -> None:
    session.add(
        SourceCorrectionFinding(
            tenant_id=tenant_id,
            company_id=company_id,
            kind=kind,
            severity=severity,
            fingerprint_ids=_uuid_list(fingerprint_ids),
            lineage_ids=_uuid_list(lineage_ids),
            import_batch_id=batch_id,
            period_from=period_from,
            period_to=period_to,
            details=details,
            created_at=at,
        )
    )


def _lineage_id_for_tx(
    session: Session, tenant_id: uuid.UUID, transaction_id: uuid.UUID
) -> uuid.UUID | None:
    return session.scalar(
        select(ImportRowLineage.id).where(
            ImportRowLineage.tenant_id == tenant_id,
            ImportRowLineage.entity_kind == "cash_transaction",
            ImportRowLineage.entity_id == transaction_id,
        )
    )


def detect_period_overlap(
    session: Session,
    fingerprint: ImportSourceFingerprint,
    batch: ImportBatch,
    at: datetime,
) -> int:
    if fingerprint.period_from is None or fingerprint.period_to is None:
        return 0
    others = session.scalars(
        select(ImportSourceFingerprint).where(
            ImportSourceFingerprint.tenant_id == fingerprint.tenant_id,
            ImportSourceFingerprint.company_id == fingerprint.company_id,
            ImportSourceFingerprint.profile_code == fingerprint.profile_code,
            ImportSourceFingerprint.id != fingerprint.id,
            ImportSourceFingerprint.period_from.isnot(None),
            ImportSourceFingerprint.period_to.isnot(None),
            ImportSourceFingerprint.period_from <= fingerprint.period_to,
            ImportSourceFingerprint.period_to >= fingerprint.period_from,
        )
    ).all()
    if not others:
        return 0
    fp_ids = [fingerprint.id, *[item.id for item in others]]
    _add_finding(
        session,
        tenant_id=fingerprint.tenant_id,
        company_id=fingerprint.company_id,
        batch_id=batch.id,
        kind="period_overlap",
        fingerprint_ids=fp_ids,
        lineage_ids=[],
        period_from=fingerprint.period_from,
        period_to=fingerprint.period_to,
        details={
            "profile_code": fingerprint.profile_code,
            "other_fingerprint_ids": _uuid_list([item.id for item in others]),
            "content_sha256": fingerprint.content_sha256,
        },
        at=at,
    )
    return 1


def detect_duplicate_suspects(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    batch: ImportBatch,
    fingerprint: ImportSourceFingerprint,
    lineage_events: list[LineageEvent],
    at: datetime,
) -> int:
    created = 0
    for event in lineage_events:
        if event.entity_kind != "cash_transaction":
            continue
        tx = session.get(CashTransaction, event.entity_id)
        if tx is None or tx.tenant_id != tenant_id:
            continue
        doc = _normalize_doc_number(tx.document_number)
        amount = money(tx.amount)
        other = session.scalar(
            select(CashTransaction.id).where(
                CashTransaction.tenant_id == tenant_id,
                CashTransaction.company_id == company_id,
                CashTransaction.id != tx.id,
                CashTransaction.direction == tx.direction,
                CashTransaction.business_date == tx.business_date,
                CashTransaction.amount == amount,
                func.coalesce(CashTransaction.document_number, "") == doc,
                CashTransaction.status == "posted",
            )
            .limit(1)
        )
        if other is None:
            continue
        peer_fp = session.scalar(
            select(ImportSourceFingerprint)
            .join(
                ImportRowLineage,
                (ImportRowLineage.tenant_id == tenant_id)
                & (ImportRowLineage.entity_kind == "cash_transaction")
                & (ImportRowLineage.entity_id == other),
            )
            .join(RawImportRow, RawImportRow.id == ImportRowLineage.raw_import_row_id)
            .where(ImportSourceFingerprint.import_batch_id == RawImportRow.batch_id)
            .limit(1)
        )
        fp_ids: list[uuid.UUID] = [fingerprint.id]
        if peer_fp is not None and peer_fp.id != fingerprint.id:
            fp_ids.append(peer_fp.id)
        lineage_ids: list[uuid.UUID] = []
        if event.row.id:
            lin = session.scalar(
                select(ImportRowLineage.id).where(
                    ImportRowLineage.tenant_id == tenant_id,
                    ImportRowLineage.raw_import_row_id == event.row.id,
                )
            )
            if lin:
                lineage_ids.append(lin)
        peer_lin = _lineage_id_for_tx(session, tenant_id, other)
        if peer_lin:
            lineage_ids.append(peer_lin)
        _add_finding(
            session,
            tenant_id=tenant_id,
            company_id=company_id,
            batch_id=batch.id,
            kind="duplicate_suspect",
            fingerprint_ids=fp_ids,
            lineage_ids=lineage_ids,
            period_from=fingerprint.period_from,
            period_to=fingerprint.period_to,
            details={
                "cash_transaction_id": str(tx.id),
                "other_transaction_id": str(other),
                "amount": str(amount),
                "business_date": tx.business_date.isoformat(),
                "direction": tx.direction,
                "document_number": doc,
            },
            at=at,
        )
        created += 1
    return created


def detect_internal_transfers(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    batch: ImportBatch,
    fingerprint: ImportSourceFingerprint,
    lineage_events: list[LineageEvent],
    at: datetime,
) -> int:
    created = 0
    for event in lineage_events:
        if event.entity_kind != "cash_transaction":
            continue
        tx = session.get(CashTransaction, event.entity_id)
        if tx is None or tx.tenant_id != tenant_id:
            continue
        reason = None
        if tx.transfer_group_id is not None:
            group = session.get(TransferGroup, tx.transfer_group_id)
            if group is not None and is_internal_transfer(group.kind, group.status):
                reason = "transfer_group"
        elif is_deposit_like_cash_description(tx.description):
            reason = "deposit_description"
        if reason is None:
            continue
        lin_id = session.scalar(
            select(ImportRowLineage.id).where(
                ImportRowLineage.tenant_id == tenant_id,
                ImportRowLineage.raw_import_row_id == event.row.id,
            )
        )
        lineage_ids = [lin_id] if lin_id else []
        _add_finding(
            session,
            tenant_id=tenant_id,
            company_id=company_id,
            batch_id=batch.id,
            kind="internal_transfer",
            fingerprint_ids=[fingerprint.id],
            lineage_ids=[item for item in lineage_ids if item],
            period_from=fingerprint.period_from,
            period_to=fingerprint.period_to,
            details={
                "cash_transaction_id": str(tx.id),
                "reason": reason,
                "transfer_group_id": str(tx.transfer_group_id) if tx.transfer_group_id else None,
            },
            at=at,
            severity="info",
        )
        created += 1
    return created


def scan_cash_corrections_after_import(
    session: Session,
    *,
    company_id: uuid.UUID,
    tenant_id: uuid.UUID,
    batch: ImportBatch,
    connection: SourceConnection,
    fingerprint: ImportSourceFingerprint,
    lineage_events: list[LineageEvent],
    at: datetime,
) -> int:
    if connection.dataset != "cash":
        return 0
    total = 0
    total += detect_period_overlap(session, fingerprint, batch, at)
    total += detect_duplicate_suspects(
        session,
        tenant_id=tenant_id,
        company_id=company_id,
        batch=batch,
        fingerprint=fingerprint,
        lineage_events=lineage_events,
        at=at,
    )
    total += detect_internal_transfers(
        session,
        tenant_id=tenant_id,
        company_id=company_id,
        batch=batch,
        fingerprint=fingerprint,
        lineage_events=lineage_events,
        at=at,
    )
    if total:
        session.flush()
    return total
