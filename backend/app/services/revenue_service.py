import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.config import Settings
from app.domain.money import money, money_str
from app.errors import AppError
from app.models.cash import CashTransaction
from app.models.identity import AuditLog, Company, IdempotencyRecord, Membership, User
from app.models.imports import SourceConnection
from app.models.revenue import Counterparty, Direction, RevenueCashMatch, RevenueEntry
from app.security.access import BILLING_MANAGER, OPERATOR
from app.services.cash_service import (
    lock_transaction_for_match,
    request_hash,
    revenue_allocated_on_cash,
)
from app.services.wallet_service import open_company
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

CREATE_SCOPE = "revenue-create"
MATCH_SCOPE = "revenue-match"


def list_directions(session: Session, company: Company) -> list[dict]:
    rows = session.scalars(
        select(Direction)
        .where(Direction.tenant_id == company.tenant_id, Direction.company_id == company.id)
        .order_by(Direction.code)
    ).all()
    return [_direction_payload(item) for item in rows]


def create_direction(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    *,
    code: str,
    name: str,
    at: datetime,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    row = Direction(
        tenant_id=company.tenant_id,
        company_id=company.id,
        code=code.strip(),
        name=name.strip(),
        created_at=at,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise AppError(409, "conflict", "Направление с таким кодом уже есть") from exc
    return _direction_payload(row)


def list_revenue(
    session: Session,
    company: Company,
    *,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> list[dict]:
    query = select(RevenueEntry).where(
        RevenueEntry.tenant_id == company.tenant_id,
        RevenueEntry.company_id == company.id,
    )
    if date_from is not None:
        query = query.where(RevenueEntry.recognition_date >= date_from)
    if date_to is not None:
        query = query.where(RevenueEntry.recognition_date <= date_to)
    rows = session.scalars(
        query.order_by(RevenueEntry.recognition_date.desc()).limit(limit).offset(offset)
    ).all()
    return [entry_payload(session, item) for item in rows]


def create_revenue(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    *,
    recognition_date: date,
    document_number: str | None,
    amount_ex_vat: str | None,
    vat_amount: str | None,
    amount_inc_vat: str,
    entry_type: str,
    vat_basis: str,
    direction_code: str | None,
    counterparty_inn: str | None,
    counterparty_name: str | None,
    external_id: str | None,
    idempotency_key: str,
    at: datetime,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    fingerprint = request_hash(
        {
            "company_id": str(company.id),
            "recognition_date": recognition_date.isoformat(),
            "document_number": document_number,
            "amount_ex_vat": amount_ex_vat,
            "vat_amount": vat_amount,
            "amount_inc_vat": amount_inc_vat,
            "entry_type": entry_type,
            "vat_basis": vat_basis,
            "direction_code": direction_code,
            "counterparty_inn": counterparty_inn,
            "counterparty_name": counterparty_name,
            "external_id": external_id,
        }
    )
    replay = _idempotent(session, user, CREATE_SCOPE, idempotency_key, fingerprint)
    if replay is not None:
        return _require_replay_company(replay.response_body, company.id)
    if entry_type not in {"sale", "return"}:
        raise AppError(422, "validation_error", "Некорректные поля продажи")
    ex_vat, vat, inc = _checked_amounts(amount_ex_vat, vat_amount, amount_inc_vat, vat_basis)
    direction = _direction(session, company, direction_code)
    party = _counterparty(session, company, counterparty_inn, counterparty_name, at)
    row = RevenueEntry(
        tenant_id=company.tenant_id,
        company_id=company.id,
        direction_id=None if direction is None else direction.id,
        counterparty_id=None if party is None else party.id,
        recognition_date=recognition_date,
        document_number=document_number,
        external_id=external_id,
        source_connection_id=None,
        import_batch_id=None,
        amount_ex_vat=ex_vat,
        vat_amount=vat,
        amount_inc_vat=inc,
        entry_type=entry_type,
        vat_basis=vat_basis,
        status="posted",
        source="manual",
        version=1,
        created_by=user.id,
        created_at=at,
        updated_at=at,
    )
    session.add(row)
    session.flush()
    payload = entry_payload(session, row)
    _remember(
        session, user, company.tenant_id, CREATE_SCOPE, idempotency_key, fingerprint, payload, at
    )
    _audit(session, user, company.tenant_id, "revenue_created", row.id, at)
    return payload


def void_revenue(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    entry_id: uuid.UUID,
    *,
    version: int,
    at: datetime,
) -> dict:
    _deny(membership)
    row = session.get(RevenueEntry, entry_id)
    if row is None or row.tenant_id != membership.tenant_id:
        raise AppError(404, "not_found", "Продажа не найдена")
    open_company(session, user, row.company_id, settings, "write")
    if row.version != version:
        raise AppError(409, "version_conflict", "Продажа уже изменена")
    if row.status == "void":
        raise AppError(422, "validation_error", "Продажа уже отменена")
    row.status = "void"
    row.version += 1
    row.updated_at = at
    session.flush()
    _audit(session, user, row.tenant_id, "revenue_voided", row.id, at)
    return entry_payload(session, row)


def create_match(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    *,
    company: Company,
    revenue_entry_id: uuid.UUID,
    cash_transaction_id: uuid.UUID,
    amount: str,
    idempotency_key: str,
    at: datetime,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    fingerprint = request_hash(
        {
            "company_id": str(company.id),
            "revenue_entry_id": str(revenue_entry_id),
            "cash_transaction_id": str(cash_transaction_id),
            "amount": amount,
        }
    )
    replay = _idempotent(session, user, MATCH_SCOPE, idempotency_key, fingerprint)
    if replay is not None:
        return _require_replay_company(replay.response_body, company.id)
    cash = lock_transaction_for_match(
        session,
        tenant_id=company.tenant_id,
        company_id=company.id,
        transaction_id=cash_transaction_id,
    )
    entry = _lock_revenue_entry(
        session,
        tenant_id=company.tenant_id,
        company_id=company.id,
        entry_id=revenue_entry_id,
    )
    if entry.status != "posted" or cash.status != "posted":
        raise AppError(422, "validation_error", "Связь только у проведённых строк")
    if entry.entry_type == "sale":
        if cash.direction != "in" or cash.currency != "RUB":
            raise AppError(422, "validation_error", "Продажу связывают с поступлением RUB")
    linked = _parse_positive(amount)
    _guard_match_amount(session, entry, cash, linked)
    row = RevenueCashMatch(
        tenant_id=company.tenant_id,
        company_id=company.id,
        revenue_entry_id=entry.id,
        cash_transaction_id=cash.id,
        amount=linked,
        created_by=user.id,
        created_at=at,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise AppError(409, "conflict", "Связь уже существует") from exc
    payload = {
        "id": str(row.id),
        "company_id": str(company.id),
        "revenue_entry_id": str(entry.id),
        "cash_transaction_id": str(cash.id),
        "amount": money_str(row.amount),
    }
    _remember(
        session, user, company.tenant_id, MATCH_SCOPE, idempotency_key, fingerprint, payload, at
    )
    _audit(session, user, company.tenant_id, "revenue_matched", row.id, at)
    return payload


def set_coverage(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    source_id: uuid.UUID,
    *,
    coverage_through: date,
    at: datetime,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    connection = session.get(SourceConnection, source_id)
    if (
        connection is None
        or connection.tenant_id != company.tenant_id
        or connection.company_id != company.id
    ):
        raise AppError(404, "not_found", "Источник не найден")
    if connection.dataset == "revenue":
        pass
    elif connection.dataset == "cash":
        pass
    else:
        raise AppError(404, "not_found", "Источник не найден")
    connection.coverage_through = coverage_through
    from app.services.dataset_coverage_service import legacy_revenue_coverage_claim

    legacy_revenue_coverage_claim(
        session, connection, coverage_through, at, timezone=company.timezone
    )
    session.flush()
    audit_action = (
        "revenue_coverage_set" if connection.dataset == "revenue" else "cash_coverage_set"
    )
    _audit(session, user, company.tenant_id, audit_action, connection.id, at)
    return {
        "id": str(connection.id),
        "dataset": connection.dataset,
        "coverage_through": coverage_through.isoformat(),
        "vat_basis": connection.vat_basis,
    }


def entry_payload(session: Session, row: RevenueEntry) -> dict:
    matched = _matched_sum(session, revenue_entry_id=row.id, cash_transaction_id=None)
    unallocated = money(row.amount_inc_vat - matched)
    links = _revenue_match_links(session, row.id)
    return {
        "id": str(row.id),
        "company_id": str(row.company_id),
        "recognition_date": row.recognition_date.isoformat(),
        "document_number": row.document_number,
        "external_id": row.external_id,
        "amount_ex_vat": None if row.amount_ex_vat is None else money_str(row.amount_ex_vat),
        "vat_amount": None if row.vat_amount is None else money_str(row.vat_amount),
        "amount_inc_vat": money_str(row.amount_inc_vat),
        "entry_type": row.entry_type,
        "vat_basis": row.vat_basis,
        "status": row.status,
        "source": row.source,
        "version": row.version,
        "direction_id": None if row.direction_id is None else str(row.direction_id),
        "counterparty_id": None if row.counterparty_id is None else str(row.counterparty_id),
        "matched_amount": money_str(matched),
        "unallocated_amount": money_str(unallocated),
        "match_links": links,
    }


def _revenue_match_links(session: Session, revenue_entry_id: uuid.UUID) -> list[dict]:
    rows = session.scalars(
        select(RevenueCashMatch).where(RevenueCashMatch.revenue_entry_id == revenue_entry_id)
    ).all()
    links: list[dict] = []
    for match in rows:
        cash = session.get(CashTransaction, match.cash_transaction_id)
        if cash is None:
            continue
        desc = cash.description or "операция"
        label = f"{cash.business_date.isoformat()} {cash.direction} {desc}"
        links.append(
            {
                "cash_transaction_id": str(cash.id),
                "amount": money_str(match.amount),
                "label": label.strip(),
            }
        )
    return links


def _lock_revenue_entry(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    entry_id: uuid.UUID,
) -> RevenueEntry:
    row = session.scalar(
        select(RevenueEntry)
        .where(
            RevenueEntry.id == entry_id,
            RevenueEntry.tenant_id == tenant_id,
            RevenueEntry.company_id == company_id,
        )
        .with_for_update()
    )
    if row is None:
        raise AppError(404, "not_found", "Продажа не найдена")
    return row


def _require_replay_company(body: dict, company_id: uuid.UUID) -> dict:
    stored = body.get("company_id")
    if stored is None:
        raise AppError(
            409,
            "idempotency_conflict",
            "Ответ без привязки к фирме; повтор с тем же ключом небезопасен, "
            "пока результат исходной операции не подтверждён",
        )
    if stored != str(company_id):
        raise AppError(409, "idempotency_conflict", "Другой payload для того же ключа")
    return body


def counterparty_id(
    session: Session,
    company: Company,
    inn: str | None,
    name: str | None,
    at: datetime,
) -> uuid.UUID | None:
    party = _counterparty(session, company, inn, name, at)
    if party is None:
        return None
    return party.id


def direction_id(session: Session, company: Company, code: str | None) -> uuid.UUID | None:
    row = _direction(session, company, code)
    if row is None:
        return None
    return row.id


def _direction(session: Session, company: Company, code: str | None) -> Direction | None:
    cleaned = (code or "").strip()
    if not cleaned:
        return None
    row = session.scalar(
        select(Direction).where(
            Direction.tenant_id == company.tenant_id,
            Direction.company_id == company.id,
            Direction.code == cleaned,
        )
    )
    if row is None:
        raise AppError(422, "validation_error", "Неизвестное направление")
    return row


def _counterparty(
    session: Session,
    company: Company,
    inn: str | None,
    name: str | None,
    at: datetime,
) -> Counterparty | None:
    cleaned = (inn or "").strip()
    if not cleaned:
        return None
    found = session.scalar(
        select(Counterparty).where(
            Counterparty.tenant_id == company.tenant_id,
            Counterparty.company_id == company.id,
            Counterparty.inn == cleaned,
        )
    )
    if found is not None:
        return found
    row = Counterparty(
        tenant_id=company.tenant_id,
        company_id=company.id,
        inn=cleaned,
        name=(name or cleaned).strip() or cleaned,
        created_at=at,
    )
    session.add(row)
    session.flush()
    return row


def _checked_amounts(
    amount_ex_vat: str | None,
    vat_amount: str | None,
    amount_inc_vat: str,
    vat_basis: str,
) -> tuple[Decimal | None, Decimal | None, Decimal]:
    if vat_basis not in {"net", "unknown"}:
        raise AppError(422, "validation_error", "Неизвестная база НДС")
    inc = _parse_positive(amount_inc_vat)
    if vat_basis == "unknown" and not (amount_ex_vat or "").strip():
        return None, None, inc
    ex_vat = _parse_non_negative(amount_ex_vat or "")
    vat = _parse_non_negative(vat_amount or "")
    if ex_vat + vat != inc:
        raise AppError(422, "validation_error", "НДС не сходится с суммой")
    return ex_vat, vat, inc


def _parse_positive(raw: str) -> Decimal:
    value = _decimal(raw)
    if value <= 0:
        raise AppError(422, "validation_error", "Сумма должна быть больше нуля")
    return value


def _parse_non_negative(raw: str) -> Decimal:
    value = _decimal(raw)
    if value < 0:
        raise AppError(422, "validation_error", "Сумма не может быть отрицательной")
    return value


def _decimal(raw: str) -> Decimal:
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise AppError(422, "validation_error", "Некорректная сумма") from exc
    if value != money(value):
        raise AppError(422, "validation_error", "Сумма задаётся до копейки")
    return money(value)


def _guard_match_amount(
    session: Session, entry: RevenueEntry, cash: CashTransaction, linked: Decimal
) -> None:
    if linked > entry.amount_inc_vat or linked > cash.amount:
        raise AppError(422, "validation_error", "Связь больше продажи или оплаты")
    revenue_used = _matched_sum(session, revenue_entry_id=entry.id, cash_transaction_id=None)
    cash_used = revenue_allocated_on_cash(session, cash.id)
    if revenue_used + linked > entry.amount_inc_vat:
        raise AppError(422, "validation_error", "Связи превышают продажу")
    if cash_used + linked > cash.amount:
        raise AppError(422, "validation_error", "Связи превышают оплату")


def _matched_sum(
    session: Session, *, revenue_entry_id: uuid.UUID | None, cash_transaction_id: uuid.UUID | None
) -> Decimal:
    query = select(func.coalesce(func.sum(RevenueCashMatch.amount), 0))
    if revenue_entry_id is not None:
        query = query.where(RevenueCashMatch.revenue_entry_id == revenue_entry_id)
    if cash_transaction_id is not None:
        query = query.where(RevenueCashMatch.cash_transaction_id == cash_transaction_id)
    value = session.scalar(query)
    if not isinstance(value, Decimal):
        return Decimal("0")
    return value


def _direction_payload(row: Direction) -> dict:
    return {"id": str(row.id), "code": row.code, "name": row.name}


def _deny(membership: Membership) -> None:
    if membership.role in {OPERATOR, BILLING_MANAGER}:
        raise AppError(403, "forbidden", "Продажи недоступны для этой роли")


def _audit(session, user, tenant_id, action: str, entity_id, at: datetime) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user.id,
            action=action,
            entity_type="revenue_entry",
            entity_id=entity_id,
            before_redacted=None,
            after_redacted=None,
            request_id=None,
            created_at=at,
        )
    )


def _idempotent(session, user, scope: str, key: str, fingerprint: str):
    row = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if row is None:
        return None
    if row.request_hash != fingerprint:
        raise AppError(409, "idempotency_conflict", "Другой payload для того же ключа")
    return row


def _remember(session, user, tenant_id, scope, key, fingerprint, payload, at) -> None:
    session.add(
        IdempotencyRecord(
            tenant_id=tenant_id,
            user_id=user.id,
            scope=scope,
            idempotency_key=key,
            request_hash=fingerprint,
            status_code=200,
            response_body=payload,
            created_at=at,
        )
    )
