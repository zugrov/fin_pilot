from datetime import datetime
from uuid import UUID

from app.api.deps import DbSession, current_session, require_csrf, settings_of, tenant_of
from app.clock import now
from app.errors import AppError
from app.models.identity import Company, Membership, User
from app.models.imports import IngestionDelivery, SourceConnection
from app.services import ingestion_http_service
from app.services.dataset_coverage_service import reconcile_delivery
from app.services.session_ingest_multipart import parse_session_ingest_multipart
from app.services.wallet_service import open_company
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

router = APIRouter(tags=["ingestions"])


class ReconcileDeliveryIn(BaseModel):
    reconciliation_basis: str = Field(min_length=1, max_length=2000)


def _post_actor(request: Request, session: Session, company_id: UUID):
    row, user = current_session(request, session)
    require_csrf(request, row)
    membership = tenant_of(request, session, user)
    _membership, company = open_company(
        session, user, company_id, settings_of(request), "write"
    )
    return user, membership, company


def _get_actor(request: Request, session: DbSession):
    _row, user = current_session(request, session)
    membership = tenant_of(request, session, user)
    return user, membership


def _accept_session_ingestion_sync(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings,
    *,
    envelope_text: str,
    file_blobs: list[bytes],
    idempotency_header: str,
    at: datetime,
) -> tuple[int, dict]:
    return ingestion_http_service.accept_session_ingestion(
        session,
        membership,
        company,
        user,
        settings,
        envelope_text=envelope_text,
        file_blobs=file_blobs,
        idempotency_header=idempotency_header,
        at=at,
    )


@router.post("/companies/{company_id}/ingestions")
async def post_session_ingestion(
    company_id: UUID,
    request: Request,
    session: DbSession,
):
    settings = settings_of(request)
    ingestion_http_service.require_session_ingest_enabled(settings)
    ingestion_http_service.reject_bearer_auth(request)

    user, membership, company = await run_in_threadpool(
        _post_actor, request, session, company_id
    )
    key = request.headers.get("idempotency-key") or request.headers.get("Idempotency-Key")
    if not key:
        raise AppError(400, "validation_error", "Нужен заголовок Idempotency-Key")

    envelope, blobs = await parse_session_ingest_multipart(request, settings)
    if len(envelope.encode("utf-8")) > settings.session_ingest_max_envelope_bytes:
        raise AppError(413, "payload_too_large", "Envelope больше лимита")

    at = now()
    status, body = await run_in_threadpool(
        _accept_session_ingestion_sync,
        session,
        membership,
        company,
        user,
        settings,
        envelope_text=envelope,
        file_blobs=blobs,
        idempotency_header=key,
        at=at,
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


@router.post("/ingestions/{delivery_id}/reconcile")
def post_reconcile_delivery(
    delivery_id: UUID,
    body: ReconcileDeliveryIn,
    request: Request,
    session: DbSession,
):
    settings = settings_of(request)
    ingestion_http_service.require_session_ingest_enabled(settings)
    ingestion_http_service.reject_bearer_auth(request)
    row, user = current_session(request, session)
    require_csrf(request, row)
    membership = tenant_of(request, session, user)
    idempotency_key = request.headers.get("idempotency-key") or request.headers.get(
        "Idempotency-Key"
    )
    if not idempotency_key:
        raise AppError(400, "validation_error", "Нужен заголовок Idempotency-Key")
    delivery = session.get(IngestionDelivery, delivery_id)
    if delivery is None or delivery.tenant_id != membership.tenant_id:
        raise AppError(404, "not_found", "Доставка не найдена")
    _membership, company = open_company(
        session, user, delivery.company_id, settings, "write"
    )
    connection = session.scalar(
        select(SourceConnection).where(
            SourceConnection.id == delivery.connection_id,
            SourceConnection.tenant_id == delivery.tenant_id,
        )
    )
    if connection is None or company is None:
        raise AppError(404, "not_found", "Источник не найден")
    at = now()
    return reconcile_delivery(
        session,
        delivery,
        connection,
        company,
        user,
        membership,
        reconciliation_basis=body.reconciliation_basis,
        idempotency_key=idempotency_key,
        at=at,
    )
