import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.config import Settings
from app.domain.billing.periods import MOSCOW
from app.domain.forecast import HORIZON_DAYS
from app.domain.money import money, money_str
from app.domain.recurrence import occurrence_dates
from app.errors import AppError
from app.models.cash import CashCategory, CashTransaction, Wallet
from app.models.identity import AuditLog, Company, IdempotencyRecord, Membership, User
from app.models.plan import (
    Obligation,
    ObligationCashLink,
    PaymentMatch,
    PlannedCashEvent,
    RecurrenceRule,
)
from app.security.access import BILLING_MANAGER, OPERATOR
from app.services.cash_service import (
    lock_transaction_for_match,
    plan_allocated_on_cash,
    request_hash,
)
from app.services.revenue_service import counterparty_id
from app.services.wallet_service import open_company
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

CREATE_SCOPE = "plan-create"
MATCH_SCOPE = "plan-match"
RULE_SCOPE = "plan-rule"
OBLIGATION_SCOPE = "plan-obligation"
CONFIDENCE = {"confirmed", "expected", "tentative"}
PRIORITY = {"critical", "high", "normal", "low"}


def list_events(session: Session, company: Company, today: date) -> list[dict]:
    rows = session.scalars(
        select(PlannedCashEvent)
        .where(
            PlannedCashEvent.tenant_id == company.tenant_id,
            PlannedCashEvent.company_id == company.id,
        )
        .order_by(PlannedCashEvent.expected_date, PlannedCashEvent.created_at)
    ).all()
    return [event_payload(session, item, today) for item in rows]


def create_event(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    *,
    direction: str,
    amount: str,
    due_date: date,
    expected_date: date,
    confidence: str,
    priority: str,
    wallet_id: uuid.UUID | None,
    category_id: uuid.UUID | None,
    counterparty_inn: str | None,
    notes: str,
    idempotency_key: str,
    at: datetime,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    fingerprint = request_hash(
        {
            "company_id": str(company.id),
            "direction": direction,
            "amount": amount,
            "due_date": due_date.isoformat(),
            "expected_date": expected_date.isoformat(),
            "confidence": confidence,
            "priority": priority,
            "wallet_id": "" if wallet_id is None else str(wallet_id),
            "category_id": "" if category_id is None else str(category_id),
            "counterparty_inn": counterparty_inn or "",
            "notes": notes,
        }
    )
    replay = _idempotent(session, user, CREATE_SCOPE, idempotency_key, fingerprint)
    if replay is not None:
        return _require_replay_company(replay.response_body, company.id)
    parsed = _amount(amount)
    _enums(direction, confidence, priority)
    _wallet(session, company, wallet_id)
    _category(session, company, category_id)
    party = counterparty_id(session, company, counterparty_inn, None, at)
    row = PlannedCashEvent(
        tenant_id=company.tenant_id,
        company_id=company.id,
        wallet_id=wallet_id,
        direction=direction,
        amount=parsed,
        currency="RUB",
        category_id=category_id,
        counterparty_id=party,
        due_date=due_date,
        expected_date=expected_date,
        confidence=confidence,
        priority=priority,
        status="planned",
        notes=notes.strip(),
        version=1,
        source="manual",
        created_by=user.id,
        created_at=at,
        updated_at=at,
    )
    session.add(row)
    session.flush()
    payload = event_payload(session, row, _local_date(at))
    _remember(
        session, user, company.tenant_id, CREATE_SCOPE, idempotency_key, fingerprint, payload, at
    )
    _audit(session, user, company.tenant_id, "plan_created", row.id, at)
    return payload


def update_event(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    event_id: uuid.UUID,
    *,
    version: int,
    at: datetime,
    change_expected: bool,
    expected_date: date | None,
    change_due: bool,
    due_date: date | None,
    amount: str | None,
    confidence: str | None,
    priority: str | None,
    notes: str | None,
) -> dict:
    _deny(membership)
    row = _owned(session, membership, event_id)
    open_company(session, user, row.company_id, settings, "write")
    if row.version != version:
        raise AppError(409, "version_conflict", "Событие уже изменено")
    if row.status == "cancelled":
        raise AppError(422, "validation_error", "Событие отменено")
    if change_expected and expected_date is not None:
        row.expected_date = expected_date
    if change_due and due_date is not None:
        row.due_date = due_date
    if amount is not None:
        parsed = _amount(amount)
        matched = posted_matched(session, row.id)
        if parsed < matched:
            raise AppError(422, "validation_error", "Сумма меньше уже оплаченной части")
        row.amount = parsed
    if confidence is not None:
        if confidence not in CONFIDENCE:
            raise AppError(422, "validation_error", "Некорректная уверенность")
        row.confidence = confidence
    if priority is not None:
        if priority not in PRIORITY:
            raise AppError(422, "validation_error", "Некорректный приоритет")
        row.priority = priority
    if notes is not None:
        row.notes = notes.strip()
    _refresh(row, posted_matched(session, row.id))
    row.version += 1
    row.updated_at = at
    session.flush()
    _audit(session, user, row.tenant_id, "plan_updated", row.id, at)
    return event_payload(session, row, _local_date(at))


def cancel_event(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    event_id: uuid.UUID,
    *,
    version: int,
    at: datetime,
) -> dict:
    _deny(membership)
    row = _owned(session, membership, event_id)
    open_company(session, user, row.company_id, settings, "write")
    if row.version != version:
        raise AppError(409, "version_conflict", "Событие уже изменено")
    row.status = "cancelled"
    row.version += 1
    row.updated_at = at
    session.flush()
    _audit(session, user, row.tenant_id, "plan_cancelled", row.id, at)
    return event_payload(session, row, _local_date(at))


def create_match(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    *,
    company: Company,
    event_id: uuid.UUID,
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
            "event_id": str(event_id),
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
    event = _lock_plan_event(
        session,
        tenant_id=company.tenant_id,
        company_id=company.id,
        event_id=event_id,
    )
    if event.status == "cancelled":
        raise AppError(404, "not_found", "Событие не найдено")
    if cash.status != "posted":
        raise AppError(422, "validation_error", "Связывать можно только проведённую операцию")
    if cash.direction != event.direction or cash.currency != event.currency:
        raise AppError(422, "validation_error", "Направление или валюта не совпадают")
    linked = _amount(amount)
    _guard_match(session, event, cash, linked)
    match = PaymentMatch(
        tenant_id=company.tenant_id,
        company_id=company.id,
        event_id=event.id,
        cash_transaction_id=cash.id,
        allocated_amount=linked,
        created_by=user.id,
        created_at=at,
    )
    session.add(match)
    try:
        session.flush()
    except IntegrityError as exc:
        raise AppError(409, "conflict", "Связь уже есть") from exc
    _refresh(event, posted_matched(session, event.id))
    event.updated_at = at
    payload = event_payload(session, event, _local_date(at))
    _remember(
        session, user, company.tenant_id, MATCH_SCOPE, idempotency_key, fingerprint, payload, at
    )
    _audit(session, user, company.tenant_id, "plan_matched", match.id, at)
    return payload


def create_recurrence(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    *,
    frequency: str,
    interval_count: int,
    day_of_month: int | None,
    start_date: date,
    end_date: date | None,
    direction: str,
    amount: str,
    confidence: str,
    priority: str,
    as_of: date,
    idempotency_key: str,
    at: datetime,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    fingerprint = request_hash(
        {
            "frequency": frequency,
            "interval": str(interval_count),
            "day": "" if day_of_month is None else str(day_of_month),
            "start": start_date.isoformat(),
            "direction": direction,
            "amount": amount,
            "as_of": as_of.isoformat(),
        }
    )
    remembered = _idempotent(session, user, RULE_SCOPE, idempotency_key, fingerprint)
    if remembered is not None:
        return remembered.response_body
    parsed = _amount(amount)
    _enums(direction, confidence, priority)
    if frequency not in {"weekly", "monthly"} or interval_count < 1:
        raise AppError(422, "validation_error", "Некорректное повторение")
    if frequency == "monthly" and (day_of_month is None or not 1 <= day_of_month <= 31):
        raise AppError(422, "validation_error", "Нужен день месяца")
    if frequency == "weekly" and day_of_month is not None:
        raise AppError(422, "validation_error", "У недели нет дня месяца")
    rule = RecurrenceRule(
        tenant_id=company.tenant_id,
        company_id=company.id,
        frequency=frequency,
        interval_count=interval_count,
        day_of_month=day_of_month,
        start_date=start_date,
        end_date=end_date,
        month_end_policy="last_day",
        direction=direction,
        amount=parsed,
        currency="RUB",
        confidence=confidence,
        priority=priority,
        notes="",
        created_at=at,
    )
    session.add(rule)
    session.flush()
    created = materialize(session, company, user, rule, as_of, at)
    payload = {"id": str(rule.id), "created": created}
    _remember(
        session, user, company.tenant_id, RULE_SCOPE, idempotency_key, fingerprint, payload, at
    )
    return payload


def generate_recurrence(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    rule_id: uuid.UUID,
    *,
    as_of: date,
    at: datetime,
) -> dict:
    _deny(membership)
    rule = session.get(RecurrenceRule, rule_id)
    if rule is None or rule.tenant_id != membership.tenant_id:
        raise AppError(404, "not_found", "Повторение не найдено")
    company = open_company(session, user, rule.company_id, settings, "write")[1]
    created = materialize(session, company, user, rule, as_of, at)
    return {"id": str(rule.id), "created": created}


def materialize(
    session: Session,
    company: Company,
    user: User,
    rule: RecurrenceRule,
    as_of: date,
    at: datetime,
) -> int:
    horizon_end = as_of + timedelta(days=HORIZON_DAYS - 1)
    dates = occurrence_dates(
        frequency=rule.frequency,
        interval_count=rule.interval_count,
        day_of_month=rule.day_of_month,
        start_date=rule.start_date,
        end_date=rule.end_date,
        as_of=as_of,
        horizon_end=horizon_end,
    )
    created = 0
    for day in dates:
        key = f"{rule.id}:{day.isoformat()}"
        exists = session.scalar(
            select(PlannedCashEvent.id).where(
                PlannedCashEvent.tenant_id == company.tenant_id,
                PlannedCashEvent.company_id == company.id,
                PlannedCashEvent.occurrence_key == key,
            )
        )
        if exists is not None:
            continue
        session.add(
            PlannedCashEvent(
                tenant_id=company.tenant_id,
                company_id=company.id,
                wallet_id=rule.wallet_id,
                direction=rule.direction,
                amount=rule.amount,
                currency=rule.currency,
                category_id=rule.category_id,
                counterparty_id=rule.counterparty_id,
                due_date=day,
                expected_date=day,
                confidence=rule.confidence,
                priority=rule.priority,
                status="planned",
                recurrence_rule_id=rule.id,
                occurrence_key=key,
                notes=rule.notes,
                version=1,
                source="manual",
                created_by=user.id,
                created_at=at,
                updated_at=at,
            )
        )
        created += 1
    session.flush()
    return created


def create_obligation(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    *,
    obligation_type: str,
    due_date: date,
    issue_date: date,
    original_amount: str,
    document_ref: str | None,
    counterparty_inn: str | None,
    idempotency_key: str,
    at: datetime,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    fingerprint = request_hash(
        {
            "type": obligation_type,
            "due": due_date.isoformat(),
            "amount": original_amount,
            "ref": document_ref or "",
        }
    )
    remembered = _idempotent(session, user, OBLIGATION_SCOPE, idempotency_key, fingerprint)
    if remembered is not None:
        return remembered.response_body
    if obligation_type not in {"receivable", "payable"}:
        raise AppError(422, "validation_error", "Некорректный тип обязательства")
    parsed = _amount(original_amount)
    party = counterparty_id(session, company, counterparty_inn, None, at)
    obligation = Obligation(
        tenant_id=company.tenant_id,
        company_id=company.id,
        obligation_type=obligation_type,
        counterparty_id=party,
        document_ref=document_ref,
        issue_date=issue_date,
        due_date=due_date,
        original_amount=parsed,
        status="open",
        created_by=user.id,
        created_at=at,
    )
    event = PlannedCashEvent(
        tenant_id=company.tenant_id,
        company_id=company.id,
        direction="in" if obligation_type == "receivable" else "out",
        amount=parsed,
        currency="RUB",
        counterparty_id=party,
        due_date=due_date,
        expected_date=due_date,
        confidence="expected",
        priority="normal",
        status="planned",
        notes=document_ref or "",
        version=1,
        source="manual",
        created_by=user.id,
        created_at=at,
        updated_at=at,
    )
    session.add(obligation)
    session.add(event)
    session.flush()
    session.add(
        ObligationCashLink(
            tenant_id=company.tenant_id,
            company_id=company.id,
            obligation_id=obligation.id,
            event_id=event.id,
            created_at=at,
        )
    )
    session.flush()
    payload = {
        "id": str(obligation.id),
        "event_id": str(event.id),
        "amount": money_str(parsed),
    }
    _remember(
        session,
        user,
        company.tenant_id,
        OBLIGATION_SCOPE,
        idempotency_key,
        fingerprint,
        payload,
        at,
    )
    return payload


def event_payload(session: Session, row: PlannedCashEvent, today: date) -> dict:
    matched = posted_matched(session, row.id)
    if row.status != "cancelled":
        _refresh(row, matched)
    remaining = money(row.amount - matched) if row.status != "cancelled" else Decimal("0.00")
    overdue = row.status != "cancelled" and remaining > 0 and row.due_date < today
    return {
        "id": str(row.id),
        "company_id": str(row.company_id),
        "direction": row.direction,
        "amount": money_str(row.amount),
        "matched": money_str(matched),
        "remaining": money_str(remaining),
        "currency": row.currency,
        "due_date": row.due_date.isoformat(),
        "expected_date": row.expected_date.isoformat(),
        "confidence": row.confidence,
        "priority": row.priority,
        "status": row.status,
        "overdue": overdue,
        "version": row.version,
        "wallet_id": None if row.wallet_id is None else str(row.wallet_id),
        "notes": row.notes,
        "match_links": _plan_match_links(session, row.id),
    }


def posted_matched(session: Session, event_id: uuid.UUID) -> Decimal:
    value = session.scalar(
        select(func.coalesce(func.sum(PaymentMatch.allocated_amount), 0))
        .join(CashTransaction, CashTransaction.id == PaymentMatch.cash_transaction_id)
        .where(
            PaymentMatch.event_id == event_id,
            CashTransaction.status == "posted",
        )
    )
    if not isinstance(value, Decimal):
        return Decimal("0.00")
    return value


def slices_for(session: Session, company: Company) -> list[tuple[PlannedCashEvent, Decimal]]:
    rows = session.scalars(
        select(PlannedCashEvent).where(
            PlannedCashEvent.tenant_id == company.tenant_id,
            PlannedCashEvent.company_id == company.id,
            PlannedCashEvent.status != "cancelled",
        )
    ).all()
    ready: list[tuple[PlannedCashEvent, Decimal]] = []
    for row in rows:
        matched = posted_matched(session, row.id)
        _refresh(row, matched)
        if row.status == "cancelled":
            continue
        ready.append((row, money(row.amount - matched)))
    return ready


def _refresh(row: PlannedCashEvent, matched: Decimal) -> None:
    if row.status == "cancelled":
        return
    if matched <= 0:
        row.status = "planned"
    elif matched < row.amount:
        row.status = "partially_paid"
    else:
        row.status = "paid"


def _guard_match(
    session: Session, event: PlannedCashEvent, cash: CashTransaction, linked: Decimal
) -> None:
    if linked > event.amount or linked > cash.amount:
        raise AppError(422, "validation_error", "Связь больше события или операции")
    event_used = posted_matched(session, event.id)
    cash_used = _cash_used(session, cash.id)
    if event_used + linked > event.amount:
        raise AppError(422, "validation_error", "Связи превышают событие")
    if cash_used + linked > cash.amount:
        raise AppError(422, "validation_error", "Связи превышают операцию")


def _cash_used(session: Session, cash_transaction_id: uuid.UUID) -> Decimal:
    return plan_allocated_on_cash(session, cash_transaction_id)


def _plan_match_links(session: Session, event_id: uuid.UUID) -> list[dict]:
    rows = session.scalars(
        select(PaymentMatch).where(PaymentMatch.event_id == event_id)
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
                "amount": money_str(match.allocated_amount),
                "label": label.strip(),
            }
        )
    return links


def _lock_plan_event(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    event_id: uuid.UUID,
) -> PlannedCashEvent:
    row = session.scalar(
        select(PlannedCashEvent)
        .where(
            PlannedCashEvent.id == event_id,
            PlannedCashEvent.tenant_id == tenant_id,
            PlannedCashEvent.company_id == company_id,
        )
        .with_for_update()
    )
    if row is None:
        raise AppError(404, "not_found", "Событие не найдено")
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


def _owned(session: Session, membership: Membership, event_id: uuid.UUID) -> PlannedCashEvent:
    row = session.get(PlannedCashEvent, event_id)
    if row is None or row.tenant_id != membership.tenant_id:
        raise AppError(404, "not_found", "Событие не найдено")
    return row


def _wallet(session: Session, company: Company, wallet_id: uuid.UUID | None) -> None:
    if wallet_id is None:
        return
    wallet = session.get(Wallet, wallet_id)
    if wallet is None or wallet.company_id != company.id or wallet.tenant_id != company.tenant_id:
        raise AppError(422, "validation_error", "Кошелёк не найден")


def _category(session: Session, company: Company, category_id: uuid.UUID | None) -> None:
    if category_id is None:
        return
    category = session.get(CashCategory, category_id)
    if category is None or category.tenant_id != company.tenant_id:
        raise AppError(422, "validation_error", "Категория не найдена")


def _enums(direction: str, confidence: str, priority: str) -> None:
    if direction not in {"in", "out"} or confidence not in CONFIDENCE or priority not in PRIORITY:
        raise AppError(422, "validation_error", "Некорректные поля плана")


def _amount(raw: str) -> Decimal:
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, AttributeError) as exc:
        raise AppError(422, "validation_error", "Некорректная сумма") from exc
    if value != money(value) or value <= 0:
        raise AppError(422, "validation_error", "Сумма задаётся до копейки и больше нуля")
    return money(value)


def _local_date(at: datetime) -> date:
    return at.astimezone(MOSCOW).date()


def _deny(membership: Membership) -> None:
    if membership.role in {OPERATOR, BILLING_MANAGER}:
        raise AppError(403, "forbidden", "План недоступен для этой роли")


def _audit(session, user, tenant_id, action: str, entity_id, at: datetime) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user.id,
            action=action,
            entity_type="planned_cash_event",
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
