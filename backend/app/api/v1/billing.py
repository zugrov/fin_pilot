from uuid import UUID

from app.api.deps import DbSession, current_session, require_csrf, settings_of, tenant_of
from app.clock import now
from app.errors import AppError
from app.services import billing_service
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

router = APIRouter(prefix="/billing", tags=["billing"])


class QuoteIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    companies: int = Field(ge=1, le=100)
    interval: str
    keep_company_ids: list[UUID] | None = None


class CheckoutIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    quote_id: UUID
    offer_accepted: bool


class ScheduleIn(BaseModel):
    interval: str | None = None
    companies: int | None = Field(default=None, ge=1, le=100)
    keep_company_ids: list[UUID] | None = None


class RefundIn(BaseModel):
    payment_attempt_id: UUID
    reason: str = Field(min_length=1, max_length=500)
    remote: dict


def _guard(request: Request, session: Session):
    row, user = current_session(request, session)
    membership = tenant_of(request, session, user)
    return row, user, membership


@router.get("/tariff")
def tariff(request: Request, session: DbSession) -> dict:
    return billing_service.tariff_view(session, now())


@router.get("/subscription")
def subscription(request: Request, session: DbSession) -> dict:
    _row, _user, membership = _guard(request, session)
    settings = settings_of(request)
    return billing_service.subscription_view(
        session, membership.tenant_id, now(), settings.billing_grace_days
    )


@router.get("/invoices")
def invoices(request: Request, session: DbSession) -> dict:
    _row, _user, membership = _guard(request, session)
    return {"invoices": billing_service.list_invoices(session, membership.tenant_id)}


@router.post("/quote")
def quote(payload: QuoteIn, request: Request, session: DbSession) -> dict:
    row, _user, membership = _guard(request, session)
    require_csrf(request, row)
    if payload.interval not in {"month", "year"}:
        raise AppError(422, "validation_error", "Неизвестный интервал")
    created = billing_service.create_quote(
        session,
        settings_of(request),
        tenant_id=membership.tenant_id,
        companies=payload.companies,
        interval=payload.interval,
        keep_company_ids=payload.keep_company_ids,
        at=now(),
    )
    return billing_service.quote_payload(created)


@router.post("/checkout")
def checkout(payload: CheckoutIn, request: Request, session: DbSession):
    row, user, membership = _guard(request, session)
    require_csrf(request, row)
    key = request.headers.get("idempotency-key")
    if not key:
        raise AppError(400, "validation_error", "Нужен заголовок Idempotency-Key")
    provider = request.app.state.payment_provider_factory()
    status, body = billing_service.checkout(
        session,
        settings_of(request),
        provider,
        user=user,
        tenant_id=membership.tenant_id,
        quote_id=payload.quote_id,
        offer_accepted=payload.offer_accepted,
        idempotency_key=key,
        at=now(),
    )
    return JSONResponse(body, status_code=status)


@router.get("/payments/{payment_id}")
def payment(payment_id: UUID, request: Request, session: DbSession) -> dict:
    _row, _user, membership = _guard(request, session)
    return billing_service.payment_view(session, membership.tenant_id, payment_id)


@router.post("/subscription/schedule-change")
def schedule(payload: ScheduleIn, request: Request, session: DbSession) -> dict:
    row, _user, membership = _guard(request, session)
    require_csrf(request, row)
    from app.security.access import assert_billing_role

    assert_billing_role(membership)
    subscription = billing_service.schedule_change(
        session,
        tenant_id=membership.tenant_id,
        interval=payload.interval,
        companies=payload.companies,
        keep_company_ids=payload.keep_company_ids,
        at=now(),
    )
    return billing_service.subscription_view(
        session, subscription.tenant_id, now(), settings_of(request).billing_grace_days
    )


@router.post("/subscription/cancel-renewal")
def cancel(request: Request, session: DbSession) -> dict:
    row, _user, membership = _guard(request, session)
    require_csrf(request, row)
    from app.security.access import assert_billing_role

    assert_billing_role(membership)
    billing_service.cancel_renewal(session, membership.tenant_id, now())
    return {"status": "ok"}


@router.post("/companies/{company_id}/activate")
def activate(company_id: UUID, request: Request, session: DbSession) -> dict:
    row, user, membership = _guard(request, session)
    require_csrf(request, row)
    if user.email_verified_at is None:
        raise AppError(403, "email_not_verified", "Подтвердите почту")
    from app.security.access import assert_billing_role

    assert_billing_role(membership)
    entitlement = billing_service.activate_company(
        session,
        tenant_id=membership.tenant_id,
        company_id=company_id,
        at=now(),
    )
    return {
        "company_id": str(entitlement.company_id),
        "active_until": entitlement.active_until.isoformat(),
        "status": entitlement.status,
    }


@router.post("/staff/refunds")
def staff_refund(payload: RefundIn, request: Request, session: DbSession) -> dict:
    row, user, membership = _guard(request, session)
    require_csrf(request, row)
    settings = settings_of(request)
    if user.normalized_email not in settings.staff_emails:
        raise AppError(403, "forbidden", "Возврат доступен только сотруднику продавца")
    refund = billing_service.apply_verified_refund(
        session,
        settings,
        tenant_id=membership.tenant_id,
        payment_attempt_id=payload.payment_attempt_id,
        remote=payload.remote,
        reason=payload.reason,
        actor=user.email,
        at=now(),
    )
    return {"id": str(refund.id), "status": refund.status, "amount": f"{refund.amount:.2f}"}
