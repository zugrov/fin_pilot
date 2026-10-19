import hashlib
import json
import uuid
from datetime import datetime
from decimal import Decimal

from app.domain.imports.budget_reader import BudgetLine
from app.domain.imports.import_meta import parse_row_meta
from app.domain.imports.prepare_common import classify_import_row
from app.domain.imports.source_identity_slot import apply_identity_watermark, load_identity_slot
from app.domain.money import money
from app.errors import AppError
from app.models.cash import CashCategory
from app.models.identity import Company, User
from app.models.imports import RawImportRow, SourceConnection, SourceIdentity
from app.models.revenue import Direction
from app.models.signals import BudgetLine as StoredLine
from app.models.signals import BudgetVersion
from app.services.budget_service import add_line, ensure_draft, revise_line
from sqlalchemy import select
from sqlalchemy.orm import Session


def prepare_budget(
    session: Session, company: Company, connection: SourceConnection, line: BudgetLine
) -> dict:
    errors = list(line.errors)
    category_id = None
    direction_id = None
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
        else:
            direction_id = str(direction.id)
    meta = parse_row_meta(line.raw, external_id=line.external_id)
    digest = "" if errors or line.amount is None else _digest(line)
    identity = None
    if meta.external_id and not errors:
        identity = load_identity_slot(session, company, connection.namespace, meta.external_id)
    classified = classify_import_row(
        errors=errors,
        meta=meta,
        identity=identity,
        entity_type="budget_line",
        payload_hash=digest,
        other_ids=(),
        authoritative=connection.authoritative,
    )
    match_id = None
    if (
        identity is not None
        and classified["duplicate_status"] == "changed"
        and identity.budget_line_id is not None
    ):
        match_id = str(identity.budget_line_id)
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
            "direction_id": direction_id,
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
    _batch_id: uuid.UUID,
    at: datetime,
) -> None:
    values = (row.normalized_payload or {})["values"]
    data = row.normalized_payload or {}
    version = ensure_draft(
        session,
        company,
        user,
        year=int(values["year"]),
        basis=values["basis"],
        at=at,
    )
    stored = add_line(
        session,
        version,
        month=int(values["month"]),
        metric_type=values["metric_type"],
        amount=_required(values["amount"]),
        category_id=_uuid(data.get("category_id")),
        direction_id=_uuid(data.get("direction_id")),
    )
    _identity(session, company, connection, row, stored.id, at)


def revise_imported(
    session: Session,
    company: Company,
    connection: SourceConnection,
    user: User,
    row: RawImportRow,
    at: datetime,
) -> None:
    data = row.normalized_payload or {}
    values = data["values"]
    current = session.get(StoredLine, uuid.UUID(data["match_id"]))
    if current is None or current.tenant_id != company.tenant_id:
        raise AppError(404, "not_found", "Строка бюджета не найдена")
    version = session.get(BudgetVersion, current.budget_version_id)
    if version is None:
        raise AppError(404, "not_found", "Бюджет не найден")
    amount = _required(values["amount"])
    if version.status == "draft":
        revise_line(session, current, version, amount)
        target_id = current.id
    else:
        draft = ensure_draft(
            session, company, user, year=int(values["year"]), basis=values["basis"], at=at
        )
        created = add_line(
            session,
            draft,
            month=int(values["month"]),
            metric_type=values["metric_type"],
            amount=amount,
            category_id=_uuid(data.get("category_id")),
            direction_id=_uuid(data.get("direction_id")),
        )
        target_id = created.id
    identity = load_identity_slot(session, company, connection.namespace, row.external_id or "")
    if identity is not None:
        identity.budget_line_id = target_id
        apply_identity_watermark(
            identity,
            source_revision=row.source_revision,
            payload_hash=row.payload_hash,
            advance_only=False,
        )
    session.flush()


def _identity(session, company, connection, row: RawImportRow, line_id: uuid.UUID, at) -> None:
    if not row.external_id or not row.payload_hash:
        return
    session.add(
        SourceIdentity(
            tenant_id=company.tenant_id,
            company_id=company.id,
            connection_id=connection.id,
            namespace=connection.namespace,
            entity_type="budget_line",
            external_id=row.external_id,
            canonical_entity_id=None,
            revenue_entry_id=None,
            planned_event_id=None,
            budget_line_id=line_id,
            payload_hash=row.payload_hash,
            last_source_revision=row.source_revision,
            created_at=at,
        )
    )


def _digest(line: BudgetLine) -> str:
    raw = json.dumps(line.canonical(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    return uuid.UUID(value)


def _required(raw: str) -> Decimal:
    value = money(Decimal(raw))
    if value < 0:
        raise AppError(422, "validation_error", "Некорректная сумма")
    return value
