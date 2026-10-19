import hashlib
import json
import uuid
from datetime import datetime

from app.domain.imports.import_meta import parse_row_meta
from app.domain.imports.prepare_common import classify_import_row
from app.domain.imports.revenue_reader import RevenueLine
from app.domain.imports.source_identity_slot import apply_identity_watermark, load_identity_slot
from app.errors import AppError
from app.models.identity import Company, User
from app.models.imports import RawImportRow, SourceConnection, SourceIdentity
from app.models.revenue import Direction, RevenueEntry
from app.services.revenue_service import counterparty_id
from sqlalchemy import select
from sqlalchemy.orm import Session


def prepare_revenue(
    session: Session, company: Company, connection: SourceConnection, line: RevenueLine
):
    errors = list(line.errors)
    direction = None
    if line.direction_code and not errors:
        direction = session.scalar(
            select(Direction).where(
                Direction.tenant_id == company.tenant_id,
                Direction.company_id == company.id,
                Direction.code == line.direction_code,
            )
        )
        if direction is None:
            errors.append("unknown_direction")
    meta = parse_row_meta(line.raw, external_id=line.external_id)
    digest = "" if errors or line.amount_inc_vat is None else _digest(line)
    identity = None
    if meta.external_id and not errors:
        identity = load_identity_slot(session, company, connection.namespace, meta.external_id)
    others: tuple[str, ...] = ()
    if identity is None and not errors and line.amount_inc_vat is not None:
        others = _other_ids(session, company, connection.namespace, line)
    classified = classify_import_row(
        errors=errors,
        meta=meta,
        identity=identity,
        entity_type="revenue_entry",
        payload_hash=digest,
        other_ids=others,
        authoritative=connection.authoritative,
    )
    match_id = others[0] if classified["duplicate_status"] == "linked" and others else None
    if (
        identity is not None
        and classified["duplicate_status"] == "changed"
        and identity.revenue_entry_id is not None
    ):
        match_id = str(identity.revenue_entry_id)
    return {
        "errors": classified["errors"],
        "duplicate_status": classified["duplicate_status"],
        "proposed_action": classified["proposed_action"],
        "payload_hash": classified["payload_hash"],
        "source_revision": classified["source_revision"],
        "operation": classified["operation"],
        "external_id": classified["external_id"],
        "normalized": {
            "values": line.canonical(),
            "direction_id": None if direction is None else str(direction.id),
            "match_id": match_id,
            "vat_basis": connection.vat_basis,
            "review_reason": classified["review_reason"],
        },
    }


def create_imported(
    session: Session,
    company: Company,
    connection: SourceConnection,
    user: User,
    row: RawImportRow,
    batch_id: uuid.UUID,
    at: datetime,
) -> None:
    values = (row.normalized_payload or {})["values"]
    data = row.normalized_payload or {}
    party = counterparty_id(session, company, values["counterparty_inn"], None, at)
    entry = RevenueEntry(
        tenant_id=company.tenant_id,
        company_id=company.id,
        direction_id=None if data.get("direction_id") is None else uuid.UUID(data["direction_id"]),
        counterparty_id=party,
        recognition_date=_date(values["recognition_date"]),
        document_number=values["document_number"] or None,
        external_id=values["external_id"] or None,
        source_connection_id=connection.id,
        import_batch_id=batch_id,
        amount_ex_vat=_optional(values["amount_ex_vat"]),
        vat_amount=_optional(values["vat_amount"]),
        amount_inc_vat=_required(values["amount_inc_vat"]),
        entry_type=values["entry_type"],
        vat_basis=data.get("vat_basis") or connection.vat_basis,
        status="posted",
        source="import",
        version=1,
        created_by=user.id,
        created_at=at,
        updated_at=at,
    )
    session.add(entry)
    session.flush()
    _identity(session, company, connection, row, entry.id, at)


def revise_imported(
    session: Session,
    company: Company,
    connection: SourceConnection,
    user: User,
    row: RawImportRow,
    at: datetime,
) -> None:
    data = row.normalized_payload or {}
    entry = session.get(RevenueEntry, uuid.UUID(data["match_id"]))
    if entry is None or entry.tenant_id != company.tenant_id:
        raise AppError(404, "not_found", "Продажа источника не найдена")
    values = data["values"]
    entry.recognition_date = _date(values["recognition_date"])
    entry.document_number = values["document_number"] or None
    entry.amount_ex_vat = _optional(values["amount_ex_vat"])
    entry.vat_amount = _optional(values["vat_amount"])
    entry.amount_inc_vat = _required(values["amount_inc_vat"])
    entry.entry_type = values["entry_type"]
    entry.vat_basis = data.get("vat_basis") or entry.vat_basis
    if data.get("direction_id"):
        entry.direction_id = uuid.UUID(data["direction_id"])
    entry.counterparty_id = counterparty_id(session, company, values["counterparty_inn"], None, at)
    entry.version += 1
    entry.updated_at = at
    identity = load_identity_slot(session, company, connection.namespace, row.external_id or "")
    if identity is not None:
        apply_identity_watermark(
            identity,
            source_revision=row.source_revision,
            payload_hash=row.payload_hash,
            advance_only=False,
        )
    session.flush()
    _ = user


def link_imported(
    session: Session,
    company: Company,
    connection: SourceConnection,
    row: RawImportRow,
    at: datetime,
) -> None:
    data = row.normalized_payload or {}
    entry = session.get(RevenueEntry, uuid.UUID(data["match_id"]))
    if entry is None or entry.tenant_id != company.tenant_id:
        raise AppError(404, "not_found", "Продажа источника не найдена")
    _identity(session, company, connection, row, entry.id, at)


def _other_ids(session, company, namespace: str, line: RevenueLine) -> tuple[str, ...]:
    rows = session.scalars(
        select(SourceIdentity.revenue_entry_id)
        .join(RevenueEntry, RevenueEntry.id == SourceIdentity.revenue_entry_id)
        .where(
            SourceIdentity.tenant_id == company.tenant_id,
            SourceIdentity.company_id == company.id,
            SourceIdentity.namespace != namespace,
            SourceIdentity.entity_type == "revenue_entry",
            RevenueEntry.status == "posted",
            RevenueEntry.recognition_date == line.recognition_date,
            RevenueEntry.amount_inc_vat == line.amount_inc_vat,
            RevenueEntry.entry_type == line.entry_type,
            RevenueEntry.document_number == (line.document_number or None),
        )
    ).all()
    return tuple(str(item) for item in rows if item is not None)


def _identity(session, company, connection, row: RawImportRow, entry_id, at: datetime) -> None:
    session.add(
        SourceIdentity(
            tenant_id=company.tenant_id,
            company_id=company.id,
            connection_id=connection.id,
            namespace=connection.namespace,
            entity_type="revenue_entry",
            external_id=row.external_id or "",
            canonical_entity_id=None,
            revenue_entry_id=entry_id,
            payload_hash=row.payload_hash or "",
            last_source_revision=row.source_revision,
            created_at=at,
        )
    )
    session.flush()


def _digest(line: RevenueLine) -> str:
    raw = json.dumps(line.canonical(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _date(raw: str):
    from datetime import date

    return date.fromisoformat(raw)


def _optional(raw: str):
    from decimal import Decimal

    if not raw:
        return None
    return Decimal(raw)


def _required(raw: str):
    from decimal import Decimal

    return Decimal(raw)
