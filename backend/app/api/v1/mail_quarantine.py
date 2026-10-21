from uuid import UUID

from app.api.deps import DbSession, current_session, require_csrf, settings_of, tenant_of
from app.clock import now
from app.errors import AppError
from app.services import mail_quarantine_api_service as quarantine_api
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(tags=["mail-quarantine"])


class CloseIn(BaseModel):
    resolution: str
    note: str = Field(default="", max_length=500)


def _idempotency_key(request: Request) -> str:
    key = request.headers.get("idempotency-key")
    if not key:
        raise AppError(400, "validation_error", "Нужен Idempotency-Key")
    return key


@router.get("/companies/{company_id}/mail-quarantine")
def list_mail_quarantine(
    company_id: UUID,
    request: Request,
    session: DbSession,
    status: str | None = None,
    limit: int = quarantine_api.DEFAULT_PAGE_LIMIT,
    offset: int = 0,
):
    row, user = current_session(request, session)
    tenant_of(request, session, user)
    membership, company = quarantine_api.open_for_read(
        session, user, company_id, settings_of(request)
    )
    rows = quarantine_api.list_entries(
        session,
        settings_of(request),
        membership=membership,
        company=company,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"entries": [quarantine_api.entry_payload(item) for item in rows]}


@router.get("/companies/{company_id}/mail-quarantine/{entry_id}")
def get_mail_quarantine(company_id: UUID, entry_id: UUID, request: Request, session: DbSession):
    row, user = current_session(request, session)
    tenant_of(request, session, user)
    membership, company = quarantine_api.open_for_read(
        session, user, company_id, settings_of(request)
    )
    entry = quarantine_api.get_entry(
        session,
        settings_of(request),
        membership=membership,
        company=company,
        entry_id=entry_id,
    )
    return {"entry": quarantine_api.entry_payload(entry)}


@router.post("/companies/{company_id}/mail-quarantine/{entry_id}/close")
def close_mail_quarantine(
    company_id: UUID,
    entry_id: UUID,
    payload: CloseIn,
    request: Request,
    session: DbSession,
):
    row, user = current_session(request, session)
    require_csrf(request, row)
    tenant_of(request, session, user)
    _membership, company = quarantine_api.open_for_write(
        session, user, company_id, settings_of(request)
    )
    result = quarantine_api.close_entry(
        session,
        settings_of(request),
        user=user,
        company=company,
        entry_id=entry_id,
        resolution=payload.resolution,
        note=payload.note,
        idempotency_key=_idempotency_key(request),
        at=now(),
    )
    return result
