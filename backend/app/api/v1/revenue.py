from datetime import date
from uuid import UUID

from app.api.deps import DbSession, current_session, require_csrf, settings_of
from app.clock import now
from app.errors import AppError
from app.services import revenue_service
from app.services.wallet_service import open_company
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

router = APIRouter(tags=["revenue"])


class DirectionIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)


class RevenueIn(BaseModel):
    recognition_date: date
    document_number: str | None = None
    amount_ex_vat: str | None = None
    vat_amount: str | None = None
    amount_inc_vat: str
    entry_type: str
    vat_basis: str = "net"
    direction_code: str | None = None
    counterparty_inn: str | None = None
    counterparty_name: str | None = None
    external_id: str | None = None
    linked_sale_entry_id: UUID | None = None


class LinkedSaleIn(BaseModel):
    linked_sale_entry_id: UUID | None = None
    version: int = Field(ge=1)


class VoidIn(BaseModel):
    version: int = Field(ge=1)


class MatchIn(BaseModel):
    company_id: UUID
    revenue_entry_id: UUID
    cash_transaction_id: UUID
    amount: str


def _actor(request: Request, session: Session, company_id: UUID, mode: str, *, mutate: bool):
    row, user = current_session(request, session)
    if mutate:
        require_csrf(request, row)
    membership, company = open_company(session, user, company_id, settings_of(request), mode)
    return user, membership, company


@router.get("/companies/{company_id}/directions")
def get_directions(company_id: UUID, request: Request, session: DbSession):
    _user, _membership, company = _actor(request, session, company_id, "read", mutate=False)
    return {"directions": revenue_service.list_directions(session, company)}


@router.post("/companies/{company_id}/directions")
def post_direction(company_id: UUID, payload: DirectionIn, request: Request, session: DbSession):
    user, membership, company = _actor(request, session, company_id, "write", mutate=True)
    return revenue_service.create_direction(
        session,
        membership,
        company,
        user,
        settings_of(request),
        code=payload.code,
        name=payload.name,
        at=now(),
    )


@router.get("/companies/{company_id}/revenue")
def get_revenue(company_id: UUID, request: Request, session: DbSession):
    _user, _membership, company = _actor(request, session, company_id, "read", mutate=False)
    date_from = _query_date(request, "date_from")
    date_to = _query_date(request, "date_to")
    return {
        "entries": revenue_service.list_revenue(
            session,
            company,
            date_from=date_from,
            date_to=date_to,
            limit=100,
            offset=0,
        )
    }


@router.post("/companies/{company_id}/revenue")
def post_revenue(company_id: UUID, payload: RevenueIn, request: Request, session: DbSession):
    user, membership, company = _actor(request, session, company_id, "write", mutate=True)
    key = request.headers.get("idempotency-key")
    if not key:
        raise AppError(400, "validation_error", "Нужен заголовок Idempotency-Key")
    return revenue_service.create_revenue(
        session,
        membership,
        company,
        user,
        settings_of(request),
        recognition_date=payload.recognition_date,
        document_number=payload.document_number,
        amount_ex_vat=payload.amount_ex_vat,
        vat_amount=payload.vat_amount,
        amount_inc_vat=payload.amount_inc_vat,
        entry_type=payload.entry_type,
        vat_basis=payload.vat_basis,
        direction_code=payload.direction_code,
        counterparty_inn=payload.counterparty_inn,
        counterparty_name=payload.counterparty_name,
        external_id=payload.external_id,
        linked_sale_entry_id=payload.linked_sale_entry_id,
        idempotency_key=key,
        at=now(),
    )


@router.patch("/companies/{company_id}/revenue/{entry_id}/linked-sale")
def patch_linked_sale(
    company_id: UUID,
    entry_id: UUID,
    payload: LinkedSaleIn,
    request: Request,
    session: DbSession,
):
    user, membership, company = _actor(request, session, company_id, "write", mutate=True)
    key = request.headers.get("idempotency-key")
    if not key:
        raise AppError(400, "validation_error", "Нужен заголовок Idempotency-Key")
    return revenue_service.set_return_linked_sale(
        session,
        membership,
        company,
        user,
        settings_of(request),
        return_entry_id=entry_id,
        linked_sale_entry_id=payload.linked_sale_entry_id,
        version=payload.version,
        idempotency_key=key,
        at=now(),
    )


@router.post("/revenue/{entry_id}/void")
def post_void(entry_id: UUID, payload: VoidIn, request: Request, session: DbSession):
    row, user = current_session(request, session)
    require_csrf(request, row)
    from app.api.deps import tenant_of

    membership = tenant_of(request, session, user)
    return revenue_service.void_revenue(
        session,
        membership,
        user,
        settings_of(request),
        entry_id,
        version=payload.version,
        at=now(),
    )


@router.post("/revenue-cash-matches")
def post_match(payload: MatchIn, request: Request, session: DbSession):
    user, membership, company = _actor(request, session, payload.company_id, "write", mutate=True)
    key = request.headers.get("idempotency-key")
    if not key:
        raise AppError(400, "validation_error", "Нужен заголовок Idempotency-Key")
    return revenue_service.create_match(
        session,
        membership,
        user,
        settings_of(request),
        company=company,
        revenue_entry_id=payload.revenue_entry_id,
        cash_transaction_id=payload.cash_transaction_id,
        amount=payload.amount,
        idempotency_key=key,
        at=now(),
    )


def _query_date(request: Request, name: str) -> date | None:
    raw = request.query_params.get(name)
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise AppError(400, "validation_error", "Некорректная дата") from exc
