import time
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.config import Settings
from app.domain.money import money
from app.errors import AppError
from app.models.cash import OpeningBalance, Wallet, WalletAccess
from app.models.identity import AuditLog, Company, IdempotencyRecord, Membership, User
from app.security.access import (
    OPERATOR,
    assert_company_paid,
    assert_finance_access,
    find_company_across_memberships,
)
from app.security.context import set_context
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

WALLET_TYPES = {"bank", "cash", "business_owner_card", "deposit", "other"}
WALLET_CREATE_SCOPE = "wallet_create"
WALLET_OPENING_SCOPE = "wallet_opening"


def parse_amount(raw: str, *, positive: bool) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise AppError(422, "validation_error", "Некорректная сумма") from exc
    if value != money(value):
        raise AppError(422, "validation_error", "Сумма должна быть с точностью до копейки")
    if positive and value <= 0:
        raise AppError(422, "validation_error", "Сумма должна быть больше нуля")
    return money(value)


def parse_moment(raw: str) -> datetime:
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        raise AppError(422, "validation_error", "Нужна временная зона")
    return moment


def open_company(
    session: Session,
    user: User,
    company_id: uuid.UUID,
    settings: Settings,
    mode: str,
) -> tuple[Membership, Company]:
    membership, company = find_company_across_memberships(session, user.id, company_id)
    if membership.role == OPERATOR:
        if mode == "analytics":
            raise AppError(403, "forbidden", "Оператору недоступна общая аналитика")
        assert_company_paid(
            session,
            membership=membership,
            company=company,
            user_verified=user.email_verified_at is not None,
            at=_now_setting(),
            mode="read" if mode == "read" else "write",
            grace_days=settings.billing_grace_days,
            bypass=settings.billing_bypass_allowed(),
        )
        return membership, company
    assert_finance_access(
        session,
        membership=membership,
        company=company,
        user_verified=user.email_verified_at is not None,
        at=_now_setting(),
        mode="read" if mode == "read" else "write",
        grace_days=settings.billing_grace_days,
        bypass=settings.billing_bypass_allowed(),
    )
    return membership, company


def _now_setting() -> datetime:
    from app.clock import now

    return now()


def create_wallet(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    *,
    name: str,
    wallet_type: str,
    availability_type: str,
    available_from: datetime | None,
    minimum_reserve: Decimal,
    masked_identifier: str | None,
    code: str | None = None,
) -> Wallet:
    if wallet_type not in WALLET_TYPES:
        raise AppError(422, "validation_error", "Неизвестный тип кошелька")
    if availability_type not in {"spendable", "restricted"}:
        raise AppError(422, "validation_error", "Неизвестный вид доступности")
    if membership.role == OPERATOR:
        raise AppError(403, "forbidden", "Оператор не создаёт кошельки")
    normalized_code = None if code is None else code.strip()
    if normalized_code == "":
        raise AppError(422, "validation_error", "Пустой код кошелька")
    moment = _now_setting()
    wallet = Wallet(
        tenant_id=company.tenant_id,
        company_id=company.id,
        name=name.strip(),
        code=normalized_code,
        type=wallet_type,
        masked_identifier=masked_identifier,
        currency="RUB",
        availability_type=availability_type,
        available_from=available_from,
        is_active=True,
        minimum_reserve=minimum_reserve,
        created_at=moment,
    )
    session.add(wallet)
    try:
        session.flush()
    except IntegrityError as exc:
        raise AppError(
            409, "duplicate_wallet_code", "Код кошелька уже занят в этой фирме"
        ) from exc
    _audit(session, user, company.tenant_id, "wallet_created", wallet.id, None, moment)
    return wallet


def list_wallets(session: Session, membership: Membership, company: Company) -> list[Wallet]:
    rows = list(
        session.scalars(
            select(Wallet)
            .where(Wallet.tenant_id == company.tenant_id, Wallet.company_id == company.id)
            .order_by(Wallet.created_at)
        ).all()
    )
    if membership.role != OPERATOR:
        return rows
    allowed = set(
        session.scalars(
            select(WalletAccess.wallet_id).where(
                WalletAccess.user_id == membership.user_id,
                WalletAccess.can_read.is_(True),
            )
        ).all()
    )
    return [row for row in rows if row.id in allowed]


def set_opening_balance(
    session: Session,
    membership: Membership,
    wallet: Wallet,
    user: User,
    *,
    effective_at: datetime,
    amount: Decimal,
) -> OpeningBalance:
    _ensure_wallet(session, membership, wallet, "write")
    current = session.scalar(
        select(OpeningBalance).where(
            OpeningBalance.wallet_id == wallet.id,
            OpeningBalance.status == "active",
        )
    )
    moment = _now_setting()
    if current is not None:
        current.status = "replaced"
        session.flush()
    opening = OpeningBalance(
        tenant_id=wallet.tenant_id,
        company_id=wallet.company_id,
        wallet_id=wallet.id,
        effective_at=effective_at,
        amount=amount,
        status="active",
        created_at=moment,
    )
    session.add(opening)
    session.flush()
    _audit(session, user, wallet.tenant_id, "opening_balance_set", opening.id, None, moment)
    return opening


def grant_wallet_access(
    session: Session,
    membership: Membership,
    wallet: Wallet,
    *,
    user_id: uuid.UUID,
    can_create: bool,
    can_read: bool,
) -> None:
    if membership.role != "owner":
        raise AppError(403, "forbidden", "Недостаточно прав")
    if wallet.tenant_id != membership.tenant_id:
        raise AppError(404, "not_found", "Кошелёк не найден")
    set_context(session, tenant_id=wallet.tenant_id, user_id=membership.user_id)
    existing = session.get(WalletAccess, (user_id, wallet.id))
    if existing is None:
        session.add(
            WalletAccess(
                tenant_id=wallet.tenant_id,
                user_id=user_id,
                wallet_id=wallet.id,
                can_create=can_create,
                can_read=can_read,
            )
        )
    else:
        existing.can_create = can_create
        existing.can_read = can_read
    session.flush()


def load_wallet(session: Session, membership: Membership, wallet_id: uuid.UUID) -> Wallet:
    wallet = session.get(Wallet, wallet_id)
    if wallet is None or wallet.tenant_id != membership.tenant_id:
        raise AppError(404, "not_found", "Кошелёк не найден")
    return wallet


def _ensure_wallet(session: Session, membership: Membership, wallet: Wallet, mode: str) -> None:
    if membership.role != OPERATOR:
        return
    access = session.get(WalletAccess, (membership.user_id, wallet.id))
    if access is None or not access.can_read:
        raise AppError(404, "not_found", "Кошелёк не найден")
    if mode == "write" and not access.can_create:
        raise AppError(403, "forbidden", "Недостаточно прав на кошелёк")


def visible_wallet(
    session: Session, membership: Membership, wallet_id: uuid.UUID, mode: str
) -> Wallet:
    wallet = load_wallet(session, membership, wallet_id)
    _ensure_wallet(session, membership, wallet, mode)
    return wallet


def _audit(session, user: User, tenant_id, action: str, entity_id, before, moment) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user.id,
            action=action,
            entity_type="wallet",
            entity_id=entity_id,
            before_redacted=before,
            after_redacted=None,
            request_id=None,
            created_at=moment,
        )
    )


def _idempotent_row(session, user: User, scope: str, key: str) -> IdempotencyRecord | None:
    return session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.idempotency_key == key,
        )
    )


def _wait_idempotent_body(
    session, user: User, scope: str, key: str, fingerprint: str
) -> dict | None:
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        session.expire_all()
        row = _idempotent_row(session, user, scope, key)
        if row is None:
            return None
        if row.request_hash != fingerprint:
            raise AppError(409, "idempotency_conflict", "Другой payload для того же ключа")
        body = row.response_body
        if not body.get("pending"):
            return body
        time.sleep(0.05)
    raise AppError(409, "conflict", "Запрос с этим ключом уже выполняется")


def _begin_idempotency(
    session,
    user: User,
    tenant_id: uuid.UUID,
    scope: str,
    key: str,
    fingerprint: str,
    at: datetime,
) -> IdempotencyRecord | dict | None:
    existing = _idempotent_row(session, user, scope, key)
    if existing is not None:
        if existing.request_hash != fingerprint:
            raise AppError(409, "idempotency_conflict", "Другой payload для того же ключа")
        body = existing.response_body
        if body.get("pending"):
            ready = _wait_idempotent_body(session, user, scope, key, fingerprint)
            if ready is not None:
                return ready
        if body.get("aborted"):
            if existing.request_hash != fingerprint:
                raise AppError(409, "idempotency_conflict", "Другой payload для того же ключа")
            existing.response_body = {"pending": True}
            existing.status_code = 200
            flag_modified(existing, "response_body")
            session.flush()
            return existing
        if body:
            return body
    record = IdempotencyRecord(
        tenant_id=tenant_id,
        user_id=user.id,
        scope=scope,
        idempotency_key=key,
        request_hash=fingerprint,
        status_code=200,
        response_body={"pending": True},
        created_at=at,
    )
    try:
        with session.begin_nested():
            session.add(record)
            session.flush()
    except IntegrityError:
        ready = _wait_idempotent_body(session, user, scope, key, fingerprint)
        if ready is not None:
            return ready
        raise
    return record


def _finalize_idempotency(record: IdempotencyRecord, payload: dict) -> None:
    record.response_body = payload
    record.status_code = 200
    flag_modified(record, "response_body")


def _abort_idempotency(record: IdempotencyRecord) -> None:
    record.response_body = {"aborted": True}
    record.status_code = 500
    flag_modified(record, "response_body")


def _validate_wallet_replay(
    session: Session,
    user: User,
    settings: Settings,
    company: Company,
    payload: dict,
) -> None:
    if payload.get("company_id") != str(company.id):
        raise AppError(409, "idempotency_conflict", "Другой payload для того же ключа")
    open_company(session, user, company.id, settings, "write")


def _validate_opening_replay(
    session: Session,
    user: User,
    settings: Settings,
    wallet: Wallet,
    payload: dict,
) -> None:
    if payload.get("wallet_id") != str(wallet.id):
        raise AppError(409, "idempotency_conflict", "Другой payload для того же ключа")
    membership, _company = open_company(session, user, wallet.company_id, settings, "write")
    _ensure_wallet(session, membership, wallet, "write")


def create_wallet_idempotent(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    *,
    name: str,
    wallet_type: str,
    availability_type: str,
    available_from: datetime | None,
    minimum_reserve: Decimal,
    masked_identifier: str | None,
    code: str | None,
    idempotency_key: str,
    fingerprint: str,
    at: datetime,
) -> dict:
    begun = _begin_idempotency(
        session,
        user,
        company.tenant_id,
        WALLET_CREATE_SCOPE,
        idempotency_key,
        fingerprint,
        at,
    )
    if isinstance(begun, dict):
        _validate_wallet_replay(session, user, settings, company, begun)
        return begun
    record = begun if isinstance(begun, IdempotencyRecord) else None
    try:
        wallet = create_wallet(
            session,
            membership,
            company,
            user,
            name=name,
            wallet_type=wallet_type,
            availability_type=availability_type,
            available_from=available_from,
            minimum_reserve=minimum_reserve,
            masked_identifier=masked_identifier,
            code=code,
        )
        from app.services import cash_service

        payload = cash_service.wallet_view(session, wallet, at)
        if record is not None:
            _finalize_idempotency(record, payload)
        return payload
    except Exception:
        if record is not None:
            _abort_idempotency(record)
            session.flush()
        raise


def opening_payload(opening: OpeningBalance) -> dict:
    return {
        "id": str(opening.id),
        "wallet_id": str(opening.wallet_id),
        "effective_at": opening.effective_at.isoformat(),
        "amount": f"{opening.amount:.2f}",
        "status": opening.status,
    }


def set_opening_balance_idempotent(
    session: Session,
    membership: Membership,
    wallet: Wallet,
    user: User,
    settings: Settings,
    *,
    effective_at: datetime,
    amount: Decimal,
    idempotency_key: str,
    fingerprint: str,
    at: datetime,
) -> dict:
    begun = _begin_idempotency(
        session,
        user,
        wallet.tenant_id,
        WALLET_OPENING_SCOPE,
        idempotency_key,
        fingerprint,
        at,
    )
    if isinstance(begun, dict):
        _validate_opening_replay(session, user, settings, wallet, begun)
        return begun
    record = begun if isinstance(begun, IdempotencyRecord) else None
    try:
        opening = set_opening_balance(
            session,
            membership,
            wallet,
            user,
            effective_at=effective_at,
            amount=amount,
        )
        payload = opening_payload(opening)
        if record is not None:
            _finalize_idempotency(record, payload)
        return payload
    except Exception:
        if record is not None:
            _abort_idempotency(record)
            session.flush()
        raise
