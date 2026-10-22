from datetime import date
from uuid import UUID

from app.api.deps import DbSession, current_session, require_csrf, settings_of
from app.clock import now
from app.services import import_service
from app.services.wallet_service import open_company
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

router = APIRouter(tags=["rules"])


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    priority: int = Field(ge=1, le=1000)
    conditions: dict
    category_code: str = Field(min_length=1, max_length=64)


class RulePreviewIn(BaseModel):
    company_id: UUID


class RulePatchIn(BaseModel):
    company_id: UUID
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    name: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def at_least_one_field(self) -> "RulePatchIn":
        if self.enabled is None and self.priority is None and self.name is None:
            raise ValueError("need at least one field to update")
        return self


class RuleApplyIn(BaseModel):
    company_id: UUID
    after_business_date: date | None = None
    after_transaction_id: UUID | None = None

    @model_validator(mode="after")
    def cursor_pair(self) -> "RuleApplyIn":
        if (self.after_business_date is None) ^ (self.after_transaction_id is None):
            raise ValueError("cursor requires business_date and transaction_id")
        return self


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


@router.patch("/rules/{rule_id}")
def patch_rule(
    rule_id: UUID,
    payload: RulePatchIn,
    request: Request,
    session: DbSession,
):
    user, membership, company = _actor(
        request, session, payload.company_id, "write", mutate=True
    )
    return import_service.update_classification_rule(
        session,
        membership,
        company,
        user,
        settings_of(request),
        rule_id,
        enabled=payload.enabled,
        priority=payload.priority,
        name=payload.name,
        at=now(),
    )


@router.post("/rules/{rule_id}/preview")
def post_preview(
    rule_id: UUID,
    payload: RulePreviewIn,
    request: Request,
    session: DbSession,
):
    _row, user = current_session(request, session)
    _user, membership, company = _actor(
        request, session, payload.company_id, "read", mutate=False
    )
    return import_service.preview_rule(
        session, membership, user, settings_of(request), company, rule_id
    )


@router.post("/rules/{rule_id}/apply")
def post_apply(
    rule_id: UUID,
    payload: RuleApplyIn,
    request: Request,
    session: DbSession,
):
    user, membership, company = _actor(
        request, session, payload.company_id, "write", mutate=True
    )
    return import_service.apply_classification_rule(
        session,
        membership,
        user,
        settings_of(request),
        company,
        rule_id,
        after_business_date=payload.after_business_date,
        after_transaction_id=payload.after_transaction_id,
        at=now(),
    )
