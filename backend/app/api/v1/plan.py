from datetime import date
from uuid import UUID

from app.api.deps import current_session, get_db, require_csrf, settings_of, tenant_of
from app.clock import now
from app.domain.billing.periods import MOSCOW
from app.errors import AppError
from app.security.access import BILLING_MANAGER, OPERATOR, companies_for
from app.services import forecast_service, plan_service
from app.services.report_service import group_cashflow_payload
from app.services.wallet_service import open_company
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

router = APIRouter(tags=["plan"])


class PlanIn(BaseModel):
    direction: str
    amount: str
    due_date: date
    expected_date: date
    confidence: str = "expected"
    priority: str = "normal"
    wallet_id: UUID | None = None
    category_id: UUID | None = None
    counterparty_inn: str | None = None
    notes: str = ""


class PlanPatch(BaseModel):
    version: int = Field(ge=1)
    expected_date: date | None = None
    due_date: date | None = None
    amount: str | None = None
    confidence: str | None = None
    priority: str | None = None
    notes: str | None = None


class CancelIn(BaseModel):
    version: int = Field(ge=1)


class MatchIn(BaseModel):
    company_id: UUID
    event_id: UUID
    cash_transaction_id: UUID
    amount: str


class RecurrenceIn(BaseModel):
    frequency: str
    interval_count: int = 1
    day_of_month: int | None = None
    start_date: date
    end_date: date | None = None
    direction: str
    amount: str
    confidence: str = "expected"
    priority: str = "normal"
    as_of: date


class GenerateIn(BaseModel):
    as_of: date


class ObligationIn(BaseModel):
    obligation_type: str
    due_date: date
    issue_date: date
    original_amount: str
    document_ref: str | None = None
    counterparty_inn: str | None = None


def _actor(request: Request, session: Session, company_id: UUID, mode: str, *, mutate: bool):
    row, user = current_session(request, session)
    if mutate:
        require_csrf(request, row)
    membership, company = open_company(session, user, company_id, settings_of(request), mode)
    return user, membership, company


def _idempotency(request: Request) -> str:
    key = request.headers.get("idempotency-key")
    if not key:
        raise AppError(400, "validation_error", "Нужен Idempotency-Key")
    return key


@router.get("/companies/{company_id}/calendar")
def get_calendar(company_id: UUID, request: Request, session: Session = Depends(get_db)):
    _user, _membership, company = _actor(request, session, company_id, "read", mutate=False)
    today = now().astimezone(MOSCOW).date()
    return {"events": plan_service.list_events(session, company, today)}


@router.post("/companies/{company_id}/planned-cash")
def post_event(
    company_id: UUID, payload: PlanIn, request: Request, session: Session = Depends(get_db)
):
    user, membership, company = _actor(request, session, company_id, "write", mutate=True)
    return plan_service.create_event(
        session,
        membership,
        company,
        user,
        settings_of(request),
        direction=payload.direction,
        amount=payload.amount,
        due_date=payload.due_date,
        expected_date=payload.expected_date,
        confidence=payload.confidence,
        priority=payload.priority,
        wallet_id=payload.wallet_id,
        category_id=payload.category_id,
        counterparty_inn=payload.counterparty_inn,
        notes=payload.notes,
        idempotency_key=_idempotency(request),
        at=now(),
    )


@router.patch("/planned-cash/{event_id}")
def patch_event(
    event_id: UUID, payload: PlanPatch, request: Request, session: Session = Depends(get_db)
):
    row, user = current_session(request, session)
    require_csrf(request, row)
    fields = payload.model_fields_set
    return plan_service.update_event(
        session,
        tenant_of(request, session, user),
        user,
        settings_of(request),
        event_id,
        version=payload.version,
        at=now(),
        change_expected="expected_date" in fields,
        expected_date=payload.expected_date,
        change_due="due_date" in fields,
        due_date=payload.due_date,
        amount=payload.amount if "amount" in fields else None,
        confidence=payload.confidence if "confidence" in fields else None,
        priority=payload.priority if "priority" in fields else None,
        notes=payload.notes if "notes" in fields else None,
    )


@router.post("/planned-cash/{event_id}/cancel")
def post_cancel(
    event_id: UUID, payload: CancelIn, request: Request, session: Session = Depends(get_db)
):
    row, user = current_session(request, session)
    require_csrf(request, row)
    return plan_service.cancel_event(
        session,
        tenant_of(request, session, user),
        user,
        settings_of(request),
        event_id,
        version=payload.version,
        at=now(),
    )


@router.post("/payment-matches")
def post_match(payload: MatchIn, request: Request, session: Session = Depends(get_db)):
    user, membership, company = _actor(
        request, session, payload.company_id, "write", mutate=True
    )
    return plan_service.create_match(
        session,
        membership,
        user,
        settings_of(request),
        company=company,
        event_id=payload.event_id,
        cash_transaction_id=payload.cash_transaction_id,
        amount=payload.amount,
        idempotency_key=_idempotency(request),
        at=now(),
    )


@router.post("/companies/{company_id}/recurrence-rules")
def post_rule(
    company_id: UUID, payload: RecurrenceIn, request: Request, session: Session = Depends(get_db)
):
    user, membership, company = _actor(request, session, company_id, "write", mutate=True)
    return plan_service.create_recurrence(
        session,
        membership,
        company,
        user,
        settings_of(request),
        frequency=payload.frequency,
        interval_count=payload.interval_count,
        day_of_month=payload.day_of_month,
        start_date=payload.start_date,
        end_date=payload.end_date,
        direction=payload.direction,
        amount=payload.amount,
        confidence=payload.confidence,
        priority=payload.priority,
        as_of=payload.as_of,
        idempotency_key=_idempotency(request),
        at=now(),
    )


@router.post("/recurrence-rules/{rule_id}/generate")
def post_generate(
    rule_id: UUID, payload: GenerateIn, request: Request, session: Session = Depends(get_db)
):
    row, user = current_session(request, session)
    require_csrf(request, row)
    return plan_service.generate_recurrence(
        session,
        tenant_of(request, session, user),
        user,
        settings_of(request),
        rule_id,
        as_of=payload.as_of,
        at=now(),
    )


@router.post("/companies/{company_id}/obligations")
def post_obligation(
    company_id: UUID, payload: ObligationIn, request: Request, session: Session = Depends(get_db)
):
    user, membership, company = _actor(request, session, company_id, "write", mutate=True)
    return plan_service.create_obligation(
        session,
        membership,
        company,
        user,
        settings_of(request),
        obligation_type=payload.obligation_type,
        due_date=payload.due_date,
        issue_date=payload.issue_date,
        original_amount=payload.original_amount,
        document_ref=payload.document_ref,
        counterparty_inn=payload.counterparty_inn,
        idempotency_key=_idempotency(request),
        at=now(),
    )


@router.get("/companies/{company_id}/forecast")
def get_forecast(company_id: UUID, request: Request, session: Session = Depends(get_db)):
    _user, _membership, company = _actor(request, session, company_id, "read", mutate=False)
    as_of = _as_of(request)
    scenario = request.query_params.get("scenario") or "base"
    return forecast_service.company_forecast(session, company, as_of, scenario, now())


@router.get("/workspaces/{tenant_id}/forecast")
def get_group_forecast(tenant_id: UUID, request: Request, session: Session = Depends(get_db)):
    _membership, chosen = _scope(tenant_id, request, session)
    scenario = request.query_params.get("scenario") or "base"
    return forecast_service.group_forecast(session, chosen, _as_of(request), scenario, now())


@router.get("/workspaces/{tenant_id}/cashflow")
def get_group_cashflow(tenant_id: UUID, request: Request, session: Session = Depends(get_db)):
    _membership, chosen = _scope(tenant_id, request, session)
    moment = now()
    return group_cashflow_payload(session, chosen, moment, _period(request, moment))


def _scope(tenant_id: UUID, request: Request, session: Session):
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
    return membership, chosen


def _as_of(request: Request) -> date:
    raw = request.query_params.get("as_of")
    if not raw:
        return now().astimezone(MOSCOW).date()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise AppError(400, "validation_error", "Некорректная дата") from exc


def _period(request: Request, at) -> tuple[date, date]:
    local = at.astimezone(MOSCOW).date()
    start = local.replace(day=1)
    end = local
    try:
        raw_from = request.query_params.get("date_from")
        raw_to = request.query_params.get("date_to")
        if raw_from:
            start = date.fromisoformat(raw_from)
        if raw_to:
            end = date.fromisoformat(raw_to)
    except ValueError as exc:
        raise AppError(400, "validation_error", "Некорректная дата") from exc
    return start, end
