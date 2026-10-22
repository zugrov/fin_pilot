from datetime import date
from uuid import UUID

from app.api.deps import DbSession, current_session, require_csrf, settings_of
from app.clock import now
from app.errors import AppError
from app.services import cash_service, wallet_service
from app.services.cash_service import request_hash
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

router = APIRouter(tags=["transactions"])


class TransactionIn(BaseModel):
    wallet_id: UUID
    business_date: date
    occurred_at: str | None = None
    direction: str
    amount: str
    category_id: UUID | None = None
    description: str = ""
    status: str = "posted"


class TransactionPatch(BaseModel):
    version: int = Field(ge=1)
    amount: str | None = None
    description: str | None = None
    business_date: date | None = None
    category_id: UUID | None = None


class VersionIn(BaseModel):
    version: int = Field(ge=1)


class ClassifyIn(BaseModel):
    version: int = Field(ge=1)
    category_id: UUID


class TransferIn(BaseModel):
    left_id: UUID
    right_id: UUID


def _company(request: Request, session: Session, company_id: UUID, mode: str, *, mutate: bool):
    row, user = current_session(request, session)
    if mutate:
        require_csrf(request, row)
    membership, company = wallet_service.open_company(
        session, user, company_id, settings_of(request), mode
    )
    return user, membership, company


@router.get("/companies/{company_id}/cash-categories")
def list_cash_categories(company_id: UUID, request: Request, session: DbSession):
    _user, _membership, company = _company(request, session, company_id, "read", mutate=False)
    return {"categories": cash_service.list_cash_categories(session, company)}


@router.get("/companies/{company_id}/transactions/unclassified/summary")
def unclassified_summary(
    company_id: UUID,
    request: Request,
    session: DbSession,
    date_from: date,
    date_to: date,
):
    _user, membership, company = _company(request, session, company_id, "read", mutate=False)
    if date_from > date_to:
        raise AppError(422, "validation_error", "Некорректный период")
    return cash_service.unclassified_summary(
        session,
        membership,
        company,
        date_from=date_from,
        date_to=date_to,
    )


@router.get("/companies/{company_id}/transactions/unclassified")
def list_unclassified_transactions(
    company_id: UUID,
    request: Request,
    session: DbSession,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    after_business_date: date | None = None,
    after_transaction_id: UUID | None = None,
):
    _user, membership, company = _company(request, session, company_id, "read", mutate=False)
    if limit < 1 or limit > cash_service.UNCLASSIFIED_MAX_LIMIT:
        raise AppError(422, "validation_error", "Некорректный лимит")
    if (after_business_date is None) ^ (after_transaction_id is None):
        raise AppError(422, "validation_error", "Курсор требует дату и идентификатор операции")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise AppError(422, "validation_error", "Некорректный период")
    rows, has_more, cursor = cash_service.list_unclassified_transactions(
        session,
        membership,
        company,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        after_business_date=after_business_date,
        after_transaction_id=after_transaction_id,
    )
    return {
        "transactions": [cash_service.transaction_payload(session, item) for item in rows],
        "has_more": has_more,
        "cursor": cursor,
    }


@router.get("/companies/{company_id}/transactions")
def list_transactions(
    company_id: UUID,
    request: Request,
    session: DbSession,
    status: str | None = None,
    wallet_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 50,
    offset: int = 0,
):
    _user, membership, company = _company(request, session, company_id, "read", mutate=False)
    if limit < 1 or limit > 200 or offset < 0:
        raise AppError(422, "validation_error", "Некорректная страница")
    rows = cash_service.list_transactions(
        session,
        membership,
        company,
        status=status,
        wallet_id=wallet_id,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return {
        "transactions": [cash_service.transaction_payload(session, item) for item in rows]
    }


@router.post("/companies/{company_id}/transactions")
def post_transaction(
    company_id: UUID,
    payload: TransactionIn,
    request: Request,
    session: DbSession,
):
    user, membership, company = _company(request, session, company_id, "write", mutate=True)
    key = request.headers.get("idempotency-key")
    if not key:
        raise AppError(400, "validation_error", "Нужен заголовок Idempotency-Key")
    body = payload.model_dump(mode="json")
    occurred = None
    if payload.occurred_at:
        occurred = wallet_service.parse_moment(payload.occurred_at)
    _status, result = cash_service.create_transaction(
        session,
        membership,
        company,
        user,
        wallet_id=payload.wallet_id,
        business_date=payload.business_date,
        occurred_at=occurred,
        direction=payload.direction,
        amount=wallet_service.parse_amount(payload.amount, positive=True),
        category_id=payload.category_id,
        description=payload.description,
        status=payload.status,
        idempotency_key=key,
        request_hash=request_hash(body),
        at=now(),
    )
    return result


@router.get("/transactions/{transaction_id}")
def get_transaction(
    transaction_id: UUID, request: Request, session: DbSession
):
    _row, user = current_session(request, session)
    from app.api.deps import tenant_of

    membership = tenant_of(request, session, user)
    row = cash_service._locked(session, membership, transaction_id, "read")
    wallet_service.open_company(session, user, row.company_id, settings_of(request), "read")
    return cash_service.transaction_payload(session, row)


@router.patch("/transactions/{transaction_id}")
def patch_transaction(
    transaction_id: UUID,
    payload: TransactionPatch,
    request: Request,
    session: DbSession,
):
    row, user = current_session(request, session)
    require_csrf(request, row)
    from app.api.deps import tenant_of

    membership = tenant_of(request, session, user)
    current = cash_service._locked(session, membership, transaction_id, "write")
    wallet_service.open_company(session, user, current.company_id, settings_of(request), "write")
    amount = None
    if payload.amount is not None:
        amount = wallet_service.parse_amount(payload.amount, positive=True)
    return cash_service.update_transaction(
        session,
        membership,
        user,
        transaction_id,
        version=payload.version,
        amount=amount,
        description=payload.description,
        business_date=payload.business_date,
        category_id=payload.category_id,
        at=now(),
    )


@router.post("/transactions/{transaction_id}/void")
def post_void(
    transaction_id: UUID,
    payload: VersionIn,
    request: Request,
    session: DbSession,
):
    row, user = current_session(request, session)
    require_csrf(request, row)
    from app.api.deps import tenant_of

    membership = tenant_of(request, session, user)
    current = cash_service._locked(session, membership, transaction_id, "write")
    wallet_service.open_company(session, user, current.company_id, settings_of(request), "write")
    return cash_service.void_transaction(
        session, membership, user, transaction_id, version=payload.version, at=now()
    )


@router.post("/transactions/{transaction_id}/classify")
def post_classify(
    transaction_id: UUID,
    payload: ClassifyIn,
    request: Request,
    session: DbSession,
):
    row, user = current_session(request, session)
    require_csrf(request, row)
    from app.api.deps import tenant_of

    membership = tenant_of(request, session, user)
    current = cash_service._locked(session, membership, transaction_id, "write")
    wallet_service.open_company(session, user, current.company_id, settings_of(request), "write")
    return cash_service.classify_transaction(
        session,
        membership,
        user,
        transaction_id,
        version=payload.version,
        category_id=payload.category_id,
        at=now(),
    )


@router.post("/transfers/link")
def post_transfer(
    payload: TransferIn, request: Request, session: DbSession
):
    row, user = current_session(request, session)
    require_csrf(request, row)
    from app.api.deps import tenant_of

    membership = tenant_of(request, session, user)
    return cash_service.link_transfer(
        session,
        membership,
        user,
        left_id=payload.left_id,
        right_id=payload.right_id,
        settings=settings_of(request),
        at=now(),
    )


@router.get("/companies/{company_id}/cash-summary")
def cash_summary(company_id: UUID, request: Request, session: DbSession):
    _user, _membership, company = _company(request, session, company_id, "analytics", mutate=False)
    summary = cash_service.company_summary(session, company, now())
    return cash_service.summary_payload(summary)
