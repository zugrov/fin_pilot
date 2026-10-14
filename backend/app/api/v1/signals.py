from datetime import date
from uuid import UUID

from app.api.deps import current_session, get_db, require_csrf, settings_of
from app.clock import now
from app.domain.billing.periods import MOSCOW
from app.errors import AppError
from app.services import alert_service, budget_service
from app.services.wallet_service import open_company
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

router = APIRouter(tags=["signals"])


class LineIn(BaseModel):
    month: int = Field(ge=1, le=12)
    metric_type: str
    amount: str
    category_id: UUID | None = None
    direction_id: UUID | None = None


class BudgetIn(BaseModel):
    name: str
    year: int
    basis: str
    lines: list[LineIn]


class ReplaceIn(BaseModel):
    lines: list[LineIn]


class RuleIn(BaseModel):
    thresholds: dict | None = None
    enabled: bool | None = None
    cooldown_minutes: int | None = None


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


def _report_date(request: Request) -> date:
    raw = request.query_params.get("report_date")
    if not raw:
        return now().astimezone(MOSCOW).date()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise AppError(400, "validation_error", "Некорректная дата") from exc


def _lines(payload: list[LineIn]) -> list[dict]:
    return [
        {
            "month": item.month,
            "metric_type": item.metric_type,
            "amount": item.amount,
            "category_id": item.category_id,
            "direction_id": item.direction_id,
        }
        for item in payload
    ]


@router.get("/companies/{company_id}/budgets")
def get_budgets(company_id: UUID, request: Request, session: Session = Depends(get_db)):
    _user, _membership, company = _actor(request, session, company_id, "read", mutate=False)
    return {"budgets": budget_service.list_budgets(session, company)}


@router.post("/companies/{company_id}/budgets")
def post_budget(
    company_id: UUID, payload: BudgetIn, request: Request, session: Session = Depends(get_db)
):
    user, membership, company = _actor(request, session, company_id, "write", mutate=True)
    return budget_service.create_budget(
        session,
        membership,
        company,
        user,
        settings_of(request),
        name=payload.name,
        year=payload.year,
        basis=payload.basis,
        lines=_lines(payload.lines),
        idempotency_key=_idempotency(request),
        at=now(),
    )


@router.patch("/budgets/{version_id}")
def patch_budget(
    version_id: UUID, payload: ReplaceIn, request: Request, session: Session = Depends(get_db)
):
    row, user = current_session(request, session)
    require_csrf(request, row)
    return budget_service.replace_budget(
        session,
        _membership_for_version(request, session, user, version_id),
        user,
        settings_of(request),
        version_id,
        lines=_lines(payload.lines),
        at=now(),
    )


@router.post("/budgets/{version_id}/approve")
def post_approve(version_id: UUID, request: Request, session: Session = Depends(get_db)):
    row, user = current_session(request, session)
    require_csrf(request, row)
    return budget_service.approve_budget(
        session,
        _membership_for_version(request, session, user, version_id),
        user,
        settings_of(request),
        version_id,
        idempotency_key=_idempotency(request),
        at=now(),
    )


@router.get("/companies/{company_id}/plan-fact")
def get_plan_fact(company_id: UUID, request: Request, session: Session = Depends(get_db)):
    _user, _membership, company = _actor(request, session, company_id, "read", mutate=False)
    return budget_service.plan_fact(session, company, _report_date(request))


@router.get("/companies/{company_id}/alerts")
def get_alerts(company_id: UUID, request: Request, session: Session = Depends(get_db)):
    _user, _membership, company = _actor(request, session, company_id, "read", mutate=False)
    return alert_service.evaluate(session, company, _report_date(request), now())


@router.post("/alerts/{alert_id}/ack")
def post_ack(alert_id: UUID, request: Request, session: Session = Depends(get_db)):
    row, user = current_session(request, session)
    require_csrf(request, row)
    from app.api.deps import tenant_of

    membership = tenant_of(request, session, user)
    return alert_service.acknowledge(
        session, membership, user, settings_of(request), alert_id, now()
    )


@router.patch("/companies/{company_id}/alert-rules/{rule_type}")
def patch_rule(
    company_id: UUID,
    rule_type: str,
    payload: RuleIn,
    request: Request,
    session: Session = Depends(get_db),
):
    user, membership, company = _actor(request, session, company_id, "write", mutate=True)
    return alert_service.update_rule(
        session,
        membership,
        user,
        settings_of(request),
        company,
        rule_type,
        thresholds=payload.thresholds,
        enabled=payload.enabled,
        cooldown_minutes=payload.cooldown_minutes,
        at=now(),
    )


def _membership_for_version(request: Request, session: Session, user, version_id: UUID):
    from app.api.deps import tenant_of
    from app.models.signals import BudgetVersion

    membership = tenant_of(request, session, user)
    version = session.get(BudgetVersion, version_id)
    if version is None or version.tenant_id != membership.tenant_id:
        raise AppError(404, "not_found", "Бюджет не найден")
    open_company(session, user, version.company_id, settings_of(request), "write")
    return membership
