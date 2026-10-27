from datetime import date
from uuid import UUID

from app.api.deps import DbSession, current_session, require_csrf, settings_of
from app.clock import now
from app.errors import AppError
from app.services import classification_pack_service as pack_service
from app.services.wallet_service import open_company
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

router = APIRouter(tags=["classification-packs"])


class PackPeriodIn(BaseModel):
    date_from: date
    date_to: date


def _actor(request: Request, session: Session, company_id: UUID, *, mutate: bool):
    row, user = current_session(request, session)
    if mutate:
        require_csrf(request, row)
    membership, company = open_company(
        session, user, company_id, settings_of(request), "write" if mutate else "read"
    )
    return user, membership, company


def _idempotency(request: Request) -> str:
    key = request.headers.get("idempotency-key")
    if not key:
        raise AppError(400, "validation_error", "Нужен Idempotency-Key")
    return key


@router.post("/companies/{company_id}/classification-packs/{slug}/{version}/preview")
def post_pack_preview(
    company_id: UUID,
    slug: str,
    version: str,
    payload: PackPeriodIn,
    request: Request,
    session: DbSession,
):
    pack_service.require_classification_packs_enabled(settings_of(request))
    _user, _membership, company = _actor(request, session, company_id, mutate=False)
    return pack_service.preview_pack(
        session,
        company,
        slug,
        version,
        date_from=payload.date_from,
        date_to=payload.date_to,
    )


@router.post("/companies/{company_id}/classification-packs/{slug}/{version}/install")
def post_pack_install(
    company_id: UUID,
    slug: str,
    version: str,
    request: Request,
    session: DbSession,
):
    pack_service.require_classification_packs_enabled(settings_of(request))
    user, membership, company = _actor(request, session, company_id, mutate=True)
    return pack_service.install_pack(
        session,
        membership,
        company,
        user,
        settings_of(request),
        slug,
        version,
        idempotency_key=_idempotency(request),
        at=now(),
    )


@router.post("/companies/{company_id}/classification-packs/{slug}/{version}/disable")
def post_pack_disable(
    company_id: UUID,
    slug: str,
    version: str,
    request: Request,
    session: DbSession,
):
    pack_service.require_classification_packs_enabled(settings_of(request))
    user, membership, company = _actor(request, session, company_id, mutate=True)
    return pack_service.disable_pack(
        session,
        membership,
        company,
        user,
        settings_of(request),
        slug,
        version,
        at=now(),
    )


@router.post("/companies/{company_id}/classification-packs/{slug}/{version}/apply")
def post_pack_apply(
    company_id: UUID,
    slug: str,
    version: str,
    request: Request,
    session: DbSession,
):
    pack_service.require_classification_packs_enabled(settings_of(request))
    user, membership, company = _actor(request, session, company_id, mutate=True)
    return pack_service.apply_pack(
        session,
        membership,
        company,
        user,
        settings_of(request),
        slug,
        version,
        at=now(),
    )
