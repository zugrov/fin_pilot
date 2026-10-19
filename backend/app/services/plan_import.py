import hashlib
import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from app.domain.imports.import_meta import parse_row_meta
from app.domain.imports.plan_reader import PlanLine
from app.domain.imports.prepare_common import classify_import_row
from app.domain.imports.source_identity_slot import apply_identity_watermark, load_identity_slot
from app.domain.money import money
from app.errors import AppError
from app.models.cash import CashCategory, Wallet
from app.models.identity import Company, User
from app.models.imports import RawImportRow, SourceConnection, SourceIdentity
from app.models.plan import PlannedCashEvent
from app.services.plan_service import posted_matched
from app.services.revenue_service import counterparty_id
from sqlalchemy import select
from sqlalchemy.orm import Session


def prepare_plan(
    session: Session, company: Company, connection: SourceConnection, line: PlanLine
) -> dict:
    errors = list(line.errors)
    category_id = None
    wallet_id = None
    if line.category_code and not errors:
        category = session.scalar(
            select(CashCategory).where(
                CashCategory.tenant_id == company.tenant_id,
                CashCategory.code == line.category_code,
            )
        )
        if category is None:
            errors.append("unknown_category")
        else:
            category_id = str(category.id)
    if line.wallet_code and not errors:
        wallet = session.scalar(
            select(Wallet).where(
                Wallet.tenant_id == company.tenant_id,
                Wallet.company_id == company.id,
                Wallet.code == line.wallet_code,
            )
        )
        if wallet is None:
            errors.append("unknown_wallet")
        else:
            wallet_id = str(wallet.id)
    meta = parse_row_meta(line.raw, external_id=line.external_id)
    digest = "" if errors or line.amount is None else _digest(line)
    identity = None
    if meta.external_id and not errors:
        identity = load_identity_slot(session, company, connection.namespace, meta.external_id)
    if identity is not None and identity.planned_event_id is not None and line.amount is not None:
        event = session.get(PlannedCashEvent, identity.planned_event_id)
        if event is not None:
            matched = posted_matched(session, event.id)
            if line.amount < matched:
                errors.append("amount_below_matched")
            if matched > 0 and line.direction != event.direction:
                errors.append("direction_locked")
            digest = "" if errors else _digest(line)
    classified = classify_import_row(
        errors=errors,
        meta=meta,
        identity=identity,
        entity_type="planned_event",
        payload_hash=digest,
        other_ids=(),
        authoritative=connection.authoritative,
    )
    match_id = None
    if (
        identity is not None
        and classified["duplicate_status"] == "changed"
        and identity.planned_event_id is not None
    ):
        match_id = str(identity.planned_event_id)
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
            "category_id": category_id,
            "wallet_id": wallet_id,
            "match_id": match_id,
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
    event = PlannedCashEvent(
        tenant_id=company.tenant_id,
        company_id=company.id,
        wallet_id=_uuid(data.get("wallet_id")),
        direction=values["direction"],
        amount=_required(values["amount"]),
        currency="RUB",
        category_id=_uuid(data.get("category_id")),
        counterparty_id=party,
        due_date=_date(values["due_date"]),
        expected_date=_date(values["expected_date"]),
        confidence=values["confidence"],
        priority=values["priority"],
        status="planned",
        notes="",
        version=1,
        source="import",
        external_id=values["external_id"] or None,
        source_connection_id=connection.id,
        import_batch_id=batch_id,
        created_by=user.id,
        created_at=at,
        updated_at=at,
    )
    session.add(event)
    session.flush()
    _identity(session, company, connection, row, event.id, at)


def revise_imported(
    session: Session,
    company: Company,
    connection: SourceConnection,
    user: User,
    row: RawImportRow,
    at: datetime,
) -> None:
    data = row.normalized_payload or {}
    event = session.get(PlannedCashEvent, uuid.UUID(data["match_id"]))
    if event is None or event.tenant_id != company.tenant_id:
        raise AppError(404, "not_found", "Событие плана не найдено")
    values = data["values"]
    matched = posted_matched(session, event.id)
    amount = _required(values["amount"])
    if amount < matched:
        raise AppError(422, "validation_error", "Сумма меньше уже оплаченной части")
    if matched > 0 and values["direction"] != event.direction:
        raise AppError(422, "validation_error", "Направление уже оплаченной части не меняется")
    event.direction = values["direction"]
    event.amount = amount
    event.due_date = _date(values["due_date"])
    event.expected_date = _date(values["expected_date"])
    event.confidence = values["confidence"]
    event.priority = values["priority"]
    event.category_id = _uuid(data.get("category_id"))
    event.wallet_id = _uuid(data.get("wallet_id"))
    event.version += 1
    event.updated_at = at
    if event.status != "cancelled":
        if matched <= 0:
            event.status = "planned"
        elif matched < event.amount:
            event.status = "partially_paid"
        else:
            event.status = "paid"
    identity = load_identity_slot(session, company, connection.namespace, row.external_id or "")
    if identity is not None:
        apply_identity_watermark(
            identity,
            source_revision=row.source_revision,
            payload_hash=row.payload_hash,
            advance_only=False,
        )
    session.flush()


def _identity(session, company, connection, row: RawImportRow, event_id: uuid.UUID, at) -> None:
    if not row.external_id or not row.payload_hash:
        return
    session.add(
        SourceIdentity(
            tenant_id=company.tenant_id,
            company_id=company.id,
            connection_id=connection.id,
            namespace=connection.namespace,
            entity_type="planned_event",
            external_id=row.external_id,
            canonical_entity_id=None,
            revenue_entry_id=None,
            planned_event_id=event_id,
            payload_hash=row.payload_hash,
            last_source_revision=row.source_revision,
            created_at=at,
        )
    )


def _digest(line: PlanLine) -> str:
    raw = json.dumps(line.canonical(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _required(value: str) -> Decimal:
    return money(Decimal(value))


def _uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    return uuid.UUID(value)
