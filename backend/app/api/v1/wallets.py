from uuid import UUID

from app.api.deps import current_session, get_db, require_csrf, settings_of, tenant_of
from app.clock import now
from app.errors import AppError
from app.models.cash import Wallet
from app.services import cash_service, wallet_service
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

router = APIRouter(tags=["wallets"])


class WalletIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str
    availability_type: str = "spendable"
    available_from: str | None = None
    minimum_reserve: str = "0.00"
    masked_identifier: str | None = Field(default=None, max_length=64)


class OpeningIn(BaseModel):
    effective_at: str
    amount: str


class WalletAccessIn(BaseModel):
    user_id: UUID
    can_create: bool = False
    can_read: bool = True


def _company(request: Request, session: Session, company_id: UUID, mode: str, *, mutate: bool):
    row, user = current_session(request, session)
    if mutate:
        require_csrf(request, row)
    membership, company = wallet_service.open_company(
        session, user, company_id, settings_of(request), mode
    )
    return user, membership, company


def _wallet(request: Request, session: Session, wallet_id: UUID, *, mutate: bool) -> tuple:
    row, user = current_session(request, session)
    if mutate:
        require_csrf(request, row)
    membership = tenant_of(request, session, user)
    wallet = session.get(Wallet, wallet_id)
    if wallet is None or wallet.tenant_id != membership.tenant_id:
        raise AppError(404, "not_found", "Кошелёк не найден")
    actor, _company = wallet_service.open_company(
        session, user, wallet.company_id, settings_of(request), "write" if mutate else "read"
    )
    return user, actor, wallet


@router.get("/companies/{company_id}/wallets")
def list_wallets(company_id: UUID, request: Request, session: Session = Depends(get_db)):
    _user, membership, company = _company(request, session, company_id, "read", mutate=False)
    rows = wallet_service.list_wallets(session, membership, company)
    return {"wallets": [cash_service.wallet_view(session, item, now()) for item in rows]}


@router.post("/companies/{company_id}/wallets")
def post_wallet(
    company_id: UUID, payload: WalletIn, request: Request, session: Session = Depends(get_db)
):
    user, membership, company = _company(request, session, company_id, "write", mutate=True)
    reserve = wallet_service.parse_amount(payload.minimum_reserve, positive=False)
    if reserve < 0:
        raise AppError(422, "validation_error", "Резерв не может быть отрицательным")
    available_from = None
    if payload.available_from:
        available_from = wallet_service.parse_moment(payload.available_from)
    wallet = wallet_service.create_wallet(
        session,
        membership,
        company,
        user,
        name=payload.name,
        wallet_type=payload.type,
        availability_type=payload.availability_type,
        available_from=available_from,
        minimum_reserve=reserve,
        masked_identifier=payload.masked_identifier,
    )
    return cash_service.wallet_view(session, wallet, now())


@router.post("/wallets/{wallet_id}/opening-balance")
def post_opening(
    wallet_id: UUID, payload: OpeningIn, request: Request, session: Session = Depends(get_db)
):
    user, membership, wallet = _wallet(request, session, wallet_id, mutate=True)
    opening = wallet_service.set_opening_balance(
        session,
        membership,
        wallet,
        user,
        effective_at=wallet_service.parse_moment(payload.effective_at),
        amount=wallet_service.parse_amount(payload.amount, positive=False),
    )
    return {
        "id": str(opening.id),
        "wallet_id": str(opening.wallet_id),
        "effective_at": opening.effective_at.isoformat(),
        "amount": f"{opening.amount:.2f}",
        "status": opening.status,
    }


@router.post("/wallets/{wallet_id}/access")
def post_access(
    wallet_id: UUID,
    payload: WalletAccessIn,
    request: Request,
    session: Session = Depends(get_db),
):
    _user, membership, wallet = _wallet(request, session, wallet_id, mutate=True)
    wallet_service.grant_wallet_access(
        session,
        membership,
        wallet,
        user_id=payload.user_id,
        can_create=payload.can_create,
        can_read=payload.can_read,
    )
    return {"status": "ok"}
