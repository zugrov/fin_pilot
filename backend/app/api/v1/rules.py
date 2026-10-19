from uuid import UUID

from app.api.deps import DbSession, current_session, require_csrf, settings_of, tenant_of
from app.clock import now
from app.services import import_service
from app.services.wallet_service import open_company
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

router = APIRouter(tags=["rules"])


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    priority: int = Field(ge=1, le=1000)
    conditions: dict
    category_code: str = Field(min_length=1, max_length=64)


class RulePreviewIn(BaseModel):
    company_id: UUID


def _actor(request: Request, session: Session, company_id: UUID, mode: str, *, mutate: bool):
    row, user = current_session(request, session)
    if mutate:
        require_csrf(request, row)
    membership, company = open_company(session, user, company_id, settings_of(request), mode)
    return user, membership, company


@router.get("/companies/{company_id}/classification-rules")
def get_rules(company_id: UUID, request: Request, session: DbSession):
    _user, _membership, company = _actor(request, session, company_id, "read", mutate=False)
    return {"rules": import_service.list_rules(session, company)}


@router.post("/companies/{company_id}/classification-rules")
def post_rule(
    company_id: UUID, payload: RuleIn, request: Request, session: DbSession
):
    user, membership, company = _actor(request, session, company_id, "write", mutate=True)
    return import_service.create_rule(
        session,
        membership,
        company,
        user,
        settings_of(request),
        name=payload.name,
        priority=payload.priority,
        conditions=payload.conditions,
        category_code=payload.category_code,
        at=now(),
    )


@router.post("/rules/{rule_id}/preview")
def post_preview(
    rule_id: UUID,
    payload: RulePreviewIn,
    request: Request,
    session: DbSession,
):
    row, user = current_session(request, session)
    require_csrf(request, row)
    tenant_of(request, session, user)
    membership, company = open_company(
        session, user, payload.company_id, settings_of(request), "read"
    )
    return import_service.preview_rule(
        session, membership, user, settings_of(request), company, rule_id
    )
