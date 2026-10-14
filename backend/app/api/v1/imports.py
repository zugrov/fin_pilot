from uuid import UUID

from app.api.deps import current_session, get_db, require_csrf, settings_of, tenant_of
from app.clock import now
from app.errors import AppError
from app.services import import_service
from app.services.wallet_service import open_company
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

router = APIRouter(tags=["imports"])


class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: str
    namespace: str = Field(min_length=1, max_length=64)
    format: str
    encoding: str = "utf-8"
    authoritative: bool = True
    wallet_id: UUID | None = None


def _actor(request: Request, session: Session, company_id: UUID, mode: str, *, mutate: bool):
    row, user = current_session(request, session)
    if mutate:
        require_csrf(request, row)
    membership, company = open_company(session, user, company_id, settings_of(request), mode)
    return user, membership, company


@router.post("/companies/{company_id}/sources")
def post_source(
    company_id: UUID, payload: SourceIn, request: Request, session: Session = Depends(get_db)
):
    user, membership, company = _actor(request, session, company_id, "write", mutate=True)
    return import_service.create_source(
        session,
        membership,
        company,
        user,
        settings_of(request),
        name=payload.name,
        source_type=payload.type,
        namespace=payload.namespace,
        file_format=payload.format,
        encoding=payload.encoding,
        authoritative=payload.authoritative,
        wallet_id=payload.wallet_id,
        at=now(),
    )


@router.get("/companies/{company_id}/sources")
def get_sources(company_id: UUID, request: Request, session: Session = Depends(get_db)):
    _user, _membership, company = _actor(request, session, company_id, "read", mutate=False)
    return {"sources": import_service.list_sources(session, company)}


@router.post("/companies/{company_id}/imports")
def post_import(
    company_id: UUID,
    request: Request,
    session: Session = Depends(get_db),
    connection_id: UUID = Form(),
    upload: UploadFile = File(),
):
    user, membership, company = _actor(request, session, company_id, "write", mutate=True)
    key = request.headers.get("idempotency-key")
    if not key:
        raise AppError(400, "validation_error", "Нужен заголовок Idempotency-Key")
    limit = settings_of(request).import_max_bytes + 1
    content = upload.file.read(limit)
    return import_service.receive_import(
        session,
        membership,
        company,
        user,
        settings_of(request),
        connection_id=connection_id,
        content=content,
        idempotency_key=key,
        at=now(),
    )


@router.get("/imports/{batch_id}/preview")
def get_preview(batch_id: UUID, request: Request, session: Session = Depends(get_db)):
    _row, user = current_session(request, session)
    membership = tenant_of(request, session, user)
    return import_service.preview_import(
        session, membership, user, settings_of(request), batch_id
    )


@router.get("/imports/{batch_id}/errors")
def get_errors(batch_id: UUID, request: Request, session: Session = Depends(get_db)):
    _row, user = current_session(request, session)
    membership = tenant_of(request, session, user)
    body = import_service.errors_csv(session, membership, user, settings_of(request), batch_id)
    return Response(content=body, media_type="text/csv; charset=utf-8")


@router.post("/imports/{batch_id}/commit")
def post_commit(batch_id: UUID, request: Request, session: Session = Depends(get_db)):
    row, user = current_session(request, session)
    require_csrf(request, row)
    membership = tenant_of(request, session, user)
    return import_service.commit_import(
        session, membership, user, settings_of(request), batch_id, now()
    )
