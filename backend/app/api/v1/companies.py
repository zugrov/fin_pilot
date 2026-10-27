import json
from datetime import date
from decimal import Decimal
from uuid import UUID

from app.api.deps import DbSession, current_session, require_csrf, settings_of, tenant_of
from app.clock import now
from app.domain.money import money_str
from app.errors import AppError
from app.models.identity import Company, IdempotencyRecord
from app.security.access import (
    BILLING_MANAGER,
    OPERATOR,
    access_row,
    assert_finance_access,
    can_write_finance,
    companies_for,
    find_company_across_memberships,
    load_company,
)
from app.security.tokens import canonical_hash
from app.services.cash_service import company_summary, summary_payload
from app.services.receivable_aging_service import (
    default_as_of,
    receivable_aging_payload,
)
from app.services.report_service import (
    cashflow_payload,
    dashboard_payload,
    default_period,
    group_revenue,
    revenue_snapshot,
)
from app.services.tenant_service import (
    create_company,
    create_workspace,
    grant_company_access,
    invite_member,
    update_company,
)
from fastapi import APIRouter, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.attributes import flag_modified

router = APIRouter(tags=["companies"])


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = "Europe/Moscow"


class CompanyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    legal_name: str | None = None
    inn: str | None = Field(default=None, max_length=12)
    kind: str = "company"


class CompanyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    legal_name: str | None = None
    min_cash_reserve: Decimal | None = None


class InviteIn(BaseModel):
    email: EmailStr
    role: str


class AccessIn(BaseModel):
    user_id: UUID
    company_id: UUID


def _company_request_hash(payload: CompanyIn) -> str:
    body = {
        "inn": payload.inn,
        "kind": payload.kind,
        "legal_name": payload.legal_name,
        "name": payload.name,
    }
    return canonical_hash(json.dumps(body, sort_keys=True, separators=(",", ":")))


def _begin_company_idempotency(session, user_id, tenant_id, key: str | None, payload: CompanyIn):
    if not key:
        return None
    request_hash = _company_request_hash(payload)
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user_id,
            IdempotencyRecord.scope == "company",
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise AppError(409, "idempotency_conflict", "Ключ уже использован с другим запросом")
        return existing.response_body
    record = IdempotencyRecord(
        tenant_id=tenant_id,
        user_id=user_id,
        scope="company",
        idempotency_key=key,
        request_hash=request_hash,
        status_code=200,
        response_body={},
        payment_attempt_id=None,
        created_at=now(),
    )
    try:
        with session.begin_nested():
            session.add(record)
            session.flush()
    except IntegrityError:
        existing = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.scope == "company",
                IdempotencyRecord.idempotency_key == key,
            )
        )
        if existing is None:
            raise
        if existing.request_hash != request_hash:
            raise AppError(
                409, "idempotency_conflict", "Ключ уже использован с другим запросом"
            ) from None
        return existing.response_body
    return record


def _company_payload(company: Company) -> dict:
    reserve = None if company.min_cash_reserve is None else f"{company.min_cash_reserve:.2f}"
    return {
        "id": str(company.id),
        "tenant_id": str(company.tenant_id),
        "name": company.name,
        "legal_name": company.legal_name,
        "inn": company.inn,
        "kind": company.kind,
        "currency": company.currency,
        "timezone": company.timezone,
        "status": company.status,
        "min_cash_reserve": reserve,
    }


@router.post("/workspaces")
def post_workspace(payload: WorkspaceIn, request: Request, session: DbSession):
    row, user = current_session(request, session)
    require_csrf(request, row)
    tenant_id = create_workspace(session, user, payload.name, payload.timezone)
    return {"id": str(tenant_id), "name": payload.name}


@router.get("/workspaces/{tenant_id}/companies")
def list_companies(tenant_id: UUID, request: Request, session: DbSession):
    _row, user = current_session(request, session)
    membership = tenant_of(request, session, user)
    if membership.tenant_id != tenant_id:
        raise AppError(404, "not_found", "Пространство не найдено")
    return {"companies": [_company_payload(item) for item in companies_for(session, membership)]}


@router.post("/workspaces/{tenant_id}/companies")
def post_company(tenant_id: UUID, payload: CompanyIn, request: Request, session: DbSession):
    row, user = current_session(request, session)
    require_csrf(request, row)
    membership = tenant_of(request, session, user)
    if membership.tenant_id != tenant_id:
        raise AppError(404, "not_found", "Пространство не найдено")
    if payload.kind not in {"company", "ip"}:
        raise AppError(422, "validation_error", "Неизвестный вид фирмы")
    key = request.headers.get("idempotency-key")
    recorded = _begin_company_idempotency(session, user.id, membership.tenant_id, key, payload)
    if isinstance(recorded, dict):
        return recorded
    company = create_company(
        session,
        membership,
        name=payload.name,
        legal_name=payload.legal_name,
        inn=payload.inn,
        kind=payload.kind,
    )
    result = _company_payload(company)
    if recorded is not None:
        recorded.response_body = result
        flag_modified(recorded, "response_body")
    return result


@router.post("/workspaces/{tenant_id}/invitations")
def post_invite(tenant_id: UUID, payload: InviteIn, request: Request, session: DbSession):
    row, user = current_session(request, session)
    require_csrf(request, row)
    membership = tenant_of(request, session, user)
    if membership.tenant_id != tenant_id:
        raise AppError(404, "not_found", "Пространство не найдено")
    invite_member(
        session,
        settings_of(request),
        membership,
        user,
        email=str(payload.email),
        role=payload.role,
    )
    return {"status": "ok"}


@router.post("/workspaces/{tenant_id}/company-access")
def post_access(tenant_id: UUID, payload: AccessIn, request: Request, session: DbSession):
    row, user = current_session(request, session)
    require_csrf(request, row)
    membership = tenant_of(request, session, user)
    if membership.tenant_id != tenant_id:
        raise AppError(404, "not_found", "Пространство не найдено")
    grant_company_access(
        session, membership, user_id=payload.user_id, company_id=payload.company_id
    )
    return {"status": "ok"}


@router.get("/workspaces/{tenant_id}/group-summary")
def group_summary(tenant_id: UUID, request: Request, session: DbSession):
    _row, user = current_session(request, session)
    membership = tenant_of(request, session, user)
    if membership.tenant_id != tenant_id:
        raise AppError(404, "not_found", "Пространство не найдено")
    if membership.role in {OPERATOR, BILLING_MANAGER}:
        raise AppError(403, "forbidden", "Общая аналитика недоступна")
    visible = companies_for(session, membership)
    requested = request.query_params.get("company_ids")
    if requested:
        wanted = {item for item in requested.split(",") if item}
        chosen = [company for company in visible if str(company.id) in wanted]
    else:
        chosen = visible
    totals: list[str | None] = []
    available: list[str | None] = []
    revenues: list[str | None] = []
    flags: list[str] = []
    moment = now()
    period = _period(request, moment)
    for company in chosen:
        payload = summary_payload(company_summary(session, company, moment))
        totals.append(payload["cash_total"])
        available.append(payload["available"])
        for flag in payload["quality_flags"]:
            if flag != "missing_revenue_source" and flag not in flags:
                flags.append(flag)
        snap = revenue_snapshot(session, company.id, company.tenant_id, period)
        revenues.append(snap["amount"])
        for flag in snap["quality_flags"]:
            if flag not in flags:
                flags.append(flag)
    if not chosen or any(item is None for item in totals):
        cash_total = None
        available_total = None
        basis = "unavailable"
    else:
        cash_total = money_str(
            sum((Decimal(item) for item in totals if item is not None), Decimal("0"))
        )
        available_total = money_str(
            sum((Decimal(item) for item in available if item is not None), Decimal("0"))
        )
        basis = "cash"
    if not chosen:
        flags = ["missing_revenue_source"]
    revenue_total, revenue_label = group_revenue(revenues)
    return {
        "scope_company_ids": [str(company.id) for company in chosen],
        "partial": len(chosen) != len(visible),
        "metrics": {
            "cash_total": cash_total,
            "available": available_total,
            "revenue": revenue_total,
        },
        "revenue_label": revenue_label,
        "quality_flags": flags,
        "metric_basis": basis,
        "company_risks": [],
    }


@router.get("/companies/{company_id}")
def get_company(company_id: UUID, request: Request, session: DbSession):
    _row, user = current_session(request, session)
    membership, company = find_company_across_memberships(session, user.id, company_id)
    _ = membership
    return _company_payload(company)


@router.patch("/companies/{company_id}")
def patch_company(
    company_id: UUID,
    payload: CompanyPatch,
    request: Request,
    session: DbSession,
):
    row, user = current_session(request, session)
    require_csrf(request, row)
    membership, company = find_company_across_memberships(session, user.id, company_id)
    settings = settings_of(request)
    writable = False
    if payload.min_cash_reserve is not None:
        assert_finance_access(
            session,
            membership=membership,
            company=company,
            user_verified=user.email_verified_at is not None,
            at=now(),
            mode="write",
            grace_days=settings.billing_grace_days,
            bypass=settings.billing_bypass_allowed(),
        )
        writable = can_write_finance(membership, access_row(session, membership, company.id))
    update_company(
        session,
        company,
        name=payload.name,
        legal_name=payload.legal_name,
        min_cash_reserve=payload.min_cash_reserve,
        can_write_finance=writable or payload.min_cash_reserve is None,
    )
    return _company_payload(company)


@router.get("/companies/{company_id}/dashboard")
def dashboard(company_id: UUID, request: Request, session: DbSession):
    _row, user = current_session(request, session)
    membership, company = find_company_across_memberships(session, user.id, company_id)
    settings = settings_of(request)
    assert_finance_access(
        session,
        membership=membership,
        company=company,
        user_verified=user.email_verified_at is not None,
        at=now(),
        mode="read",
        grace_days=settings.billing_grace_days,
        bypass=settings.billing_bypass_allowed(),
    )
    moment = now()
    return dashboard_payload(session, company, moment, _period(request, moment))


@router.get("/companies/{company_id}/reports/receivable-aging")
def receivable_aging(company_id: UUID, request: Request, session: DbSession):
    _row, user = current_session(request, session)
    membership, company = find_company_across_memberships(session, user.id, company_id)
    settings = settings_of(request)
    assert_finance_access(
        session,
        membership=membership,
        company=company,
        user_verified=user.email_verified_at is not None,
        at=now(),
        mode="read",
        grace_days=settings.billing_grace_days,
        bypass=settings.billing_bypass_allowed(),
    )
    moment = now()
    as_of = _as_of_date(request, company, moment)
    return receivable_aging_payload(
        session,
        company,
        as_of=as_of,
        max_rows=settings.receivable_aging_max_rows,
    )


@router.get("/companies/{company_id}/cashflow")
def cashflow(company_id: UUID, request: Request, session: DbSession):
    _row, user = current_session(request, session)
    membership, company = find_company_across_memberships(session, user.id, company_id)
    settings = settings_of(request)
    assert_finance_access(
        session,
        membership=membership,
        company=company,
        user_verified=user.email_verified_at is not None,
        at=now(),
        mode="read",
        grace_days=settings.billing_grace_days,
        bypass=settings.billing_bypass_allowed(),
    )
    return cashflow_payload(session, company, now(), _period(request, now()))


def _as_of_date(request: Request, company: Company, at) -> date:
    raw = request.query_params.get("as_of")
    if not raw:
        return default_as_of(at, company.timezone)
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise AppError(422, "validation_error", "Некорректная дата as_of") from exc


def _period(request: Request, at) -> tuple[date, date]:
    start, end = default_period(at)
    raw_from = request.query_params.get("date_from")
    raw_to = request.query_params.get("date_to")
    try:
        if raw_from:
            start = date.fromisoformat(raw_from)
        if raw_to:
            end = date.fromisoformat(raw_to)
    except ValueError as exc:
        raise AppError(400, "validation_error", "Некорректная дата") from exc
    return start, end


@router.get("/companies/{company_id}/export")
def export_company(company_id: UUID, request: Request, session: DbSession):
    _row, user = current_session(request, session)
    membership, company = find_company_across_memberships(session, user.id, company_id)
    settings = settings_of(request)
    assert_finance_access(
        session,
        membership=membership,
        company=company,
        user_verified=user.email_verified_at is not None,
        at=now(),
        mode="read",
        grace_days=settings.billing_grace_days,
        bypass=settings.billing_bypass_allowed(),
    )
    return {"company_id": str(company.id), "quality_flags": ["missing_opening_balance"], "rows": []}


_ = (load_company, select)
