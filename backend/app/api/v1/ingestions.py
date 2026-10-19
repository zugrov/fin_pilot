from uuid import UUID

from app.api.deps import DbSession, current_session, require_csrf, settings_of, tenant_of
from app.clock import now
from app.errors import AppError
from app.services import ingestion_http_service
from app.services.session_ingest_multipart import parse_session_ingest_multipart
from app.services.wallet_service import open_company
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(tags=["ingestions"])


def _post_actor(request: Request, session: DbSession, company_id: UUID):
    row, user = current_session(request, session)
    require_csrf(request, row)
    membership = tenant_of(request, session, user)
    _membership, company = open_company(
        session, user, company_id, settings_of(request), "write"
    )
    return row, user, membership, company


def _get_actor(request: Request, session: DbSession):
    _row, user = current_session(request, session)
    membership = tenant_of(request, session, user)
    return user, membership


@router.post("/companies/{company_id}/ingestions")
async def post_session_ingestion(
    company_id: UUID,
    request: Request,
    session: DbSession,
):
    settings = settings_of(request)
    ingestion_http_service.require_session_ingest_enabled(settings)
    ingestion_http_service.reject_bearer_auth(request)
    _row, user, membership, company = _post_actor(request, session, company_id)
    key = request.headers.get("idempotency-key") or request.headers.get("Idempotency-Key")
    if not key:
        raise AppError(400, "validation_error", "Нужен заголовок Idempotency-Key")

    envelope, blobs = await parse_session_ingest_multipart(request, settings)
    if len(envelope.encode("utf-8")) > settings.session_ingest_max_envelope_bytes:
        raise AppError(413, "payload_too_large", "Envelope больше лимита")

    status, body = ingestion_http_service.accept_session_ingestion(
        session,
        membership,
        company,
        user,
        settings,
        envelope_text=envelope,
        file_blobs=blobs,
        idempotency_header=key,
        at=now(),
    )
    return JSONResponse(status_code=status, content=body)


@router.get("/ingestions/{delivery_id}")
def get_session_ingestion(delivery_id: UUID, request: Request, session: DbSession):
    settings = settings_of(request)
    ingestion_http_service.require_session_ingest_enabled(settings)
    ingestion_http_service.reject_bearer_auth(request)
    user, membership = _get_actor(request, session)
    body = ingestion_http_service.get_session_delivery(
        session, membership, user, settings, delivery_id
    )
    return body
