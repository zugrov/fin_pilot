import uuid
from datetime import datetime
from urllib.parse import urlparse

from app.config import Settings
from app.errors import AppError
from app.models.identity import EmailOutbox
from sqlalchemy import select
from sqlalchemy.orm import Session


def build_link(settings: Settings, path: str) -> str:
    base = settings.public_base_url.rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AppError(500, "config", "PUBLIC_BASE_URL задан неверно")
    if not path.startswith("/"):
        path = "/" + path
    return f"{base}{path}"


def enqueue_email(
    session: Session,
    *,
    category: str,
    type_: str,
    to_email: str,
    template_key: str,
    payload: dict,
    idempotency_key: str,
    created_at: datetime,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    company_id: uuid.UUID | None = None,
) -> EmailOutbox:
    existing = session.scalar(
        select(EmailOutbox).where(EmailOutbox.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return existing
    row = EmailOutbox(
        category=category,
        type=type_,
        to_email=to_email,
        template_key=template_key,
        payload_redacted=payload,
        idempotency_key=idempotency_key,
        status="pending",
        attempts=0,
        created_at=created_at,
        tenant_id=tenant_id,
        user_id=user_id,
        company_id=company_id,
    )
    session.add(row)
    session.flush()
    return row
