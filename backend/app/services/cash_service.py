import json
import uuid
from datetime import date, datetime
from decimal import Decimal

from app.config import Settings
from app.domain.cash.balance import Anchor, CashLine, WalletInput
from app.domain.cash.summary import CashSummary, summarize
from app.domain.money import money_str
from app.errors import AppError
from app.models.cash import (
    CashCategory,
    CashTransaction,
    OpeningBalance,
    TransactionRevision,
    TransferGroup,
    Wallet,
)
from app.models.identity import AuditLog, Company, IdempotencyRecord, Membership, User
from app.security.access import OPERATOR
from app.security.tokens import canonical_hash
from app.services.wallet_service import visible_wallet
from sqlalchemy import select, text
from sqlalchemy.orm import Session

SCOPE = "cash-create"


def company_summary(session: Session, company: Company, at: datetime) -> CashSummary:
    wallets = list(
        session.scalars(
            select(Wallet).where(
                Wallet.tenant_id == company.tenant_id,
                Wallet.company_id == company.id,
                Wallet.is_active.is_(True),
            )
        ).all()
    )
    inputs = tuple(_wallet_input(session, wallet) for wallet in wallets)
    reserve = _reserve(company, wallets, at)
    if not inputs:
        return CashSummary(
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            ("missing_anchor", "missing_revenue_source"),
        )
    return summarize(inputs, at, reserve)


def list_transactions(
    session: Session,
    membership: Membership,
    company: Company,
    *,
    status: str | None,
    wallet_id: uuid.UUID | None,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> list[CashTransaction]:
    query = select(CashTransaction).where(
        CashTransaction.tenant_id == company.tenant_id,
        CashTransaction.company_id == company.id,
    )
    if status:
        query = query.where(CashTransaction.status == status)
    if wallet_id:
        query = query.where(CashTransaction.wallet_id == wallet_id)
    if date_from:
        query = query.where(CashTransaction.business_date >= date_from)
    if date_to:
        query = query.where(CashTransaction.business_date <= date_to)
    if membership.role == OPERATOR:
        allowed = _operator_wallets(session, membership)
        if not allowed:
            return []
        query = query.where(CashTransaction.wallet_id.in_(allowed))
    query = query.order_by(CashTransaction.business_date.desc()).limit(limit).offset(offset)
    return list(session.scalars(query).all())


def create_transaction(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    *,
    wallet_id: uuid.UUID,
    business_date: date,
    occurred_at: datetime | None,
    direction: str,
    amount: Decimal,
    category_id: uuid.UUID | None,
    description: str,
    status: str,
    idempotency_key: str,
    request_hash: str,
    at: datetime,
    source: str = "manual",
) -> tuple[int, dict]:
    existing = _idempotent(session, user, idempotency_key, request_hash)
    if existing is not None:
        return existing.status_code, existing.response_body
    if direction not in {"in", "out"} or status not in {"draft", "posted"}:
        raise AppError(422, "validation_error", "Некорректные поля операции")
    if source not in {"manual", "import", "telegram"}:
        raise AppError(422, "validation_error", "Некорректный источник операции")
    wallet = visible_wallet(session, membership, wallet_id, "write")
    if wallet.company_id != company.id:
        raise AppError(404, "not_found", "Кошелёк не найден")
    _category(session, company.tenant_id, category_id)
    row = CashTransaction(
        tenant_id=company.tenant_id,
        company_id=company.id,
        wallet_id=wallet.id,
        business_date=business_date,
        occurred_at=occurred_at,
        direction=direction,
        amount=amount,
        currency="RUB",
        category_id=category_id,
        description=description,
        source=source,
        status=status,
        classification_origin="manual" if category_id else "none",
        locked_classification=category_id is not None,
        created_by=user.id,
        version=1,
        created_at=at,
        updated_at=at,
    )
    session.add(row)
    session.flush()
    _audit(session, user, company.tenant_id, "transaction_created", row.id, at)
    payload = transaction_payload(row)
    _remember(session, user, company.tenant_id, idempotency_key, request_hash, payload, at)
    return 200, payload


def update_transaction(
    session: Session,
    membership: Membership,
    user: User,
    transaction_id: uuid.UUID,
    *,
    version: int,
    amount: Decimal | None,
    description: str | None,
    business_date: date | None,
    category_id: uuid.UUID | None,
    at: datetime,
) -> dict:
    row = _locked(session, membership, transaction_id, "write")
    if row.version != version:
        raise AppError(409, "version_conflict", "Операция уже изменена")
    if row.status == "void":
        raise AppError(422, "validation_error", "Отменённую операцию нельзя менять")
    _remember_revision(session, row, user, at)
    if amount is not None:
        row.amount = amount
    if description is not None:
        row.description = description
    if business_date is not None:
        row.business_date = business_date
    if category_id is not None:
        _category(session, row.tenant_id, category_id)
        row.category_id = category_id
    row.version += 1
    row.updated_at = at
    session.flush()
    _audit(session, user, row.tenant_id, "transaction_updated", row.id, at)
    return transaction_payload(row)


def void_transaction(
    session: Session,
    membership: Membership,
    user: User,
    transaction_id: uuid.UUID,
    *,
    version: int,
    at: datetime,
) -> dict:
    row = _locked(session, membership, transaction_id, "write")
    if row.version != version:
        raise AppError(409, "version_conflict", "Операция уже изменена")
    if row.status == "void":
        return transaction_payload(row)
    _remember_revision(session, row, user, at)
    row.status = "void"
    row.version += 1
    row.updated_at = at
    session.flush()
    _audit(session, user, row.tenant_id, "transaction_void", row.id, at)
    return transaction_payload(row)


def classify_transaction(
    session: Session,
    membership: Membership,
    user: User,
    transaction_id: uuid.UUID,
    *,
    version: int,
    category_id: uuid.UUID,
    at: datetime,
) -> dict:
    row = _locked(session, membership, transaction_id, "write")
    if row.version != version:
        raise AppError(409, "version_conflict", "Операция уже изменена")
    _category(session, row.tenant_id, category_id)
    _remember_revision(session, row, user, at)
    row.category_id = category_id
    row.classification_origin = "manual"
    row.locked_classification = True
    row.version += 1
    row.updated_at = at
    session.flush()
    _audit(session, user, row.tenant_id, "transaction_classified", row.id, at)
    return transaction_payload(row)


def link_transfer(
    session: Session,
    membership: Membership,
    user: User,
    *,
    left_id: uuid.UUID,
    right_id: uuid.UUID,
    settings: Settings,
    at: datetime,
) -> dict:
    from app.services.wallet_service import open_company

    left_row = session.get(CashTransaction, left_id)
    right_row = session.get(CashTransaction, right_id)
    if left_row is None or right_row is None:
        raise AppError(404, "not_found", "Операция не найдена")
    if left_row.tenant_id != membership.tenant_id or right_row.tenant_id != membership.tenant_id:
        raise AppError(404, "not_found", "Операция не найдена")
    open_company(session, user, left_row.company_id, settings, "write")
    open_company(session, user, right_row.company_id, settings, "write")
    left = _locked(session, membership, left_id, "write")
    right = _locked(session, membership, right_id, "write")
    if left.id == right.id or left.status != "posted" or right.status != "posted":
        raise AppError(422, "validation_error", "Нужны две проведённые операции")
    if left.transfer_group_id or right.transfer_group_id:
        raise AppError(409, "conflict", "Операция уже входит в перевод")
    if left.amount != right.amount or left.currency != right.currency:
        raise AppError(422, "validation_error", "Сумма и валюта ног должны совпадать")
    if left.direction == right.direction:
        raise AppError(422, "validation_error", "Направления ног должны быть противоположны")
    if left.company_id != right.company_id and membership.role == OPERATOR:
        raise AppError(403, "forbidden", "Оператор не связывает фирмы")
    kind = "internal" if left.company_id == right.company_id else "intercompany"
    group = TransferGroup(
        tenant_id=left.tenant_id,
        kind=kind,
        status="linked",
        pairing_method="manual",
        confirmed_by=user.id,
        amount=left.amount,
        currency=left.currency,
        created_at=at,
    )
    session.add(group)
    session.flush()
    for row in (left, right):
        _remember_revision(session, row, user, at)
        row.transfer_group_id = group.id
        row.version += 1
        row.updated_at = at
    session.flush()
    _audit(session, user, left.tenant_id, "transfer_linked", group.id, at)
    return {"id": str(group.id), "kind": group.kind, "amount": money_str(group.amount)}


def summary_payload(summary: CashSummary) -> dict:
    def shown(value: Decimal | None) -> str | None:
        return None if value is None else money_str(value)

    return {
        "cash_total": shown(summary.cash_total),
        "available": shown(summary.available),
        "restricted": shown(summary.restricted),
        "headroom": shown(summary.headroom),
        "external_in": shown(summary.external_in),
        "external_out": shown(summary.external_out),
        "financing_in": shown(summary.financing_in),
        "revenue": None,
        "quality_flags": list(summary.quality_flags),
        "metric_basis": "cash" if summary.cash_total is not None else "unavailable",
    }


def _active_opening(session: Session, wallet: Wallet) -> dict | None:
    opening = session.scalar(
        select(OpeningBalance).where(
            OpeningBalance.wallet_id == wallet.id,
            OpeningBalance.status == "active",
        )
    )
    if opening is None:
        return None
    return {
        "amount": money_str(opening.amount),
        "effective_at": opening.effective_at.isoformat(),
    }


def wallet_view(session: Session, wallet: Wallet, at: datetime) -> dict:
    from app.domain.cash.balance import wallet_balance

    view = wallet_balance(_wallet_input(session, wallet), at)
    return {
        "id": str(wallet.id),
        "company_id": str(wallet.company_id),
        "name": wallet.name,
        "code": wallet.code,
        "type": wallet.type,
        "currency": wallet.currency,
        "availability_type": wallet.availability_type,
        "available_from": (
            None if wallet.available_from is None else wallet.available_from.isoformat()
        ),
        "minimum_reserve": money_str(wallet.minimum_reserve),
        "is_active": wallet.is_active,
        "balance": None if view.amount is None else money_str(view.amount),
        "quality_flags": list(view.quality_flags),
        "active_opening": _active_opening(session, wallet),
    }


def transaction_payload(row: CashTransaction) -> dict:
    return {
        "id": str(row.id),
        "company_id": str(row.company_id),
        "wallet_id": str(row.wallet_id),
        "business_date": row.business_date.isoformat(),
        "occurred_at": None if row.occurred_at is None else row.occurred_at.isoformat(),
        "direction": row.direction,
        "amount": money_str(row.amount),
        "currency": row.currency,
        "category_id": None if row.category_id is None else str(row.category_id),
        "description": row.description,
        "status": row.status,
        "version": row.version,
        "transfer_group_id": None if row.transfer_group_id is None else str(row.transfer_group_id),
        "locked_classification": row.locked_classification,
    }


def request_hash(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return canonical_hash(raw)


def _wallet_input(session: Session, wallet: Wallet) -> WalletInput:
    opening = session.scalar(
        select(OpeningBalance).where(
            OpeningBalance.wallet_id == wallet.id,
            OpeningBalance.status == "active",
        )
    )
    anchor = None
    if opening is not None:
        anchor = Anchor(opening.effective_at, opening.amount)
    rows = session.scalars(
        select(CashTransaction).where(CashTransaction.wallet_id == wallet.id)
    ).all()
    lines = tuple(_line(session, row) for row in rows)
    return WalletInput(
        anchor,
        wallet.availability_type,
        wallet.available_from,
        wallet.minimum_reserve,
        lines,
    )


def _line(session: Session, row: CashTransaction) -> CashLine:
    section = None
    if row.category_id is not None:
        category = session.get(CashCategory, row.category_id)
        if category is not None:
            section = category.cash_flow_section
    kind = None
    if row.transfer_group_id is not None:
        group = session.get(TransferGroup, row.transfer_group_id)
        if group is not None and group.status == "linked":
            kind = group.kind
    return CashLine(
        row.direction,
        row.amount,
        row.status,
        row.business_date,
        row.occurred_at,
        kind,
        section,
    )


def _reserve(company: Company, wallets: list[Wallet], at: datetime) -> Decimal:
    if company.min_cash_reserve is not None:
        return company.min_cash_reserve
    total = Decimal("0")
    for wallet in wallets:
        item = _wallet_input_light(wallet)
        if item.availability_type == "spendable" or (
            item.available_from is not None and item.available_from <= at
        ):
            total += wallet.minimum_reserve
    return total


def _wallet_input_light(wallet: Wallet) -> WalletInput:
    return WalletInput(
        None,
        wallet.availability_type,
        wallet.available_from,
        wallet.minimum_reserve,
        (),
    )


def _operator_wallets(session: Session, membership: Membership) -> list[uuid.UUID]:
    from app.models.cash import WalletAccess

    return list(
        session.scalars(
            select(WalletAccess.wallet_id).where(
                WalletAccess.user_id == membership.user_id,
                WalletAccess.can_read.is_(True),
            )
        ).all()
    )


def _category(session: Session, tenant_id: uuid.UUID, category_id: uuid.UUID | None) -> None:
    if category_id is None:
        return
    category = session.get(CashCategory, category_id)
    if category is None or category.tenant_id != tenant_id:
        raise AppError(404, "not_found", "Категория не найдена")


def _locked(session, membership, transaction_id, mode: str) -> CashTransaction:
    row = session.get(CashTransaction, transaction_id)
    if row is None or row.tenant_id != membership.tenant_id:
        raise AppError(404, "not_found", "Операция не найдена")
    from app.security.access import OWNER, companies_for

    if membership.role != OPERATOR and membership.role != OWNER:
        visible = {item.id for item in companies_for(session, membership)}
        if row.company_id not in visible:
            raise AppError(404, "not_found", "Операция не найдена")
    visible_wallet(session, membership, row.wallet_id, mode)
    return row


def _remember_revision(session, row: CashTransaction, user: User, at: datetime) -> None:
    if row.status != "posted":
        return
    session.execute(text("SELECT set_config('app.cash_revision', 'on', true)"))
    session.add(
        TransactionRevision(
            tenant_id=row.tenant_id,
            transaction_id=row.id,
            version=row.version,
            previous={
                "amount": money_str(row.amount),
                "direction": row.direction,
                "status": row.status,
                "business_date": row.business_date.isoformat(),
                "wallet_id": str(row.wallet_id),
                "category_id": None if row.category_id is None else str(row.category_id),
                "transfer_group_id": (
                    None if row.transfer_group_id is None else str(row.transfer_group_id)
                ),
            },
            created_by=user.id,
            created_at=at,
        )
    )


def _idempotent(session, user: User, key: str, request_hash: str) -> IdempotencyRecord | None:
    row = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.scope == SCOPE,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if row is None:
        return None
    if row.request_hash != request_hash:
        raise AppError(409, "idempotency_conflict", "Другой payload для того же ключа")
    return row


def _remember(session, user, tenant_id, key, request_hash, payload, at) -> None:
    session.add(
        IdempotencyRecord(
            tenant_id=tenant_id,
            user_id=user.id,
            scope=SCOPE,
            idempotency_key=key,
            request_hash=request_hash,
            status_code=200,
            response_body=payload,
            created_at=at,
        )
    )


def _audit(session, user: User, tenant_id, action: str, entity_id, at: datetime) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user.id,
            action=action,
            entity_type="cash_transaction",
            entity_id=entity_id,
            before_redacted=None,
            after_redacted=None,
            request_id=None,
            created_at=at,
        )
    )
