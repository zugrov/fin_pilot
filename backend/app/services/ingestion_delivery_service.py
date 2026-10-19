"""Transport layer: IngestionDelivery и части (FA-R02.1)."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.errors import AppError
from app.integrations.imap_client import MailAttachment
from app.models.identity import Company
from app.models.imports import (
    ImportBatch,
    IngestionDelivery,
    IngestionDeliveryPart,
    SourceConnection,
)
from app.security.tokens import canonical_hash
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

STATUS_PARTIAL = "partially_received"
STATUS_COMPLETE = "transport_complete"
STATUS_DUPLICATE = "duplicate_transport"
STATUS_REJECTED = "transport_rejected"

PART_PENDING = "pending"
PART_PREVIEW = "preview"
PART_FAILED = "failed"
PART_IGNORED = "ignored"
PART_SKIPPED = "skipped"


@dataclass(frozen=True)
class TransportContext:
    delivery_id: uuid.UUID
    part_id: uuid.UUID


def ui_delivery_key(user_id: uuid.UUID, idempotency_key: str) -> str:
    return f"ui:{user_id}:{idempotency_key}"


def mail_delivery_key(connection_id: uuid.UUID, uidvalidity: int, uid: int) -> str:
    return f"mail:{connection_id}:{uidvalidity}:{uid}"


def mail_part_idempotency_key(
    connection_id: uuid.UUID, uidvalidity: int, uid: int, part_index: int, content_hash: str
) -> str:
    return f"mail:{connection_id}:{uidvalidity}:{uid}:{part_index}:{content_hash}"


def ui_request_fingerprint(connection_id: uuid.UUID, content_hash: str) -> str:
    return canonical_hash(f"{connection_id}:ui:1:{content_hash}")


def manifest_fingerprint(connection_id: uuid.UUID, parts: list[tuple[int, str]]) -> str:
    ordered = sorted(parts, key=lambda item: item[0])
    body = ";".join(f"{index}:{digest}" for index, digest in ordered)
    return canonical_hash(f"{connection_id}:mail:{body}")


def resolve_delivery(
    session: Session,
    company: Company,
    connection: SourceConnection,
    *,
    channel: str,
    delivery_key: str,
    request_fingerprint: str,
    at: datetime,
) -> IngestionDelivery:
    existing = session.scalar(
        select(IngestionDelivery).where(
            IngestionDelivery.tenant_id == company.tenant_id,
            IngestionDelivery.company_id == company.id,
            IngestionDelivery.connection_id == connection.id,
            IngestionDelivery.delivery_key == delivery_key,
        )
    )
    if existing is not None:
        if existing.request_fingerprint != request_fingerprint:
            raise AppError(
                409,
                "delivery_conflict",
                "Другой состав доставки для того же transport-ключа",
            )
        return existing
    row = IngestionDelivery(
        id=uuid.uuid4(),
        tenant_id=company.tenant_id,
        company_id=company.id,
        connection_id=connection.id,
        channel=channel,
        delivery_key=delivery_key,
        request_fingerprint=request_fingerprint,
        transport_status=STATUS_PARTIAL,
        created_at=at,
        updated_at=at,
    )
    session.add(row)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        found = session.scalar(
            select(IngestionDelivery).where(
                IngestionDelivery.tenant_id == company.tenant_id,
                IngestionDelivery.company_id == company.id,
                IngestionDelivery.connection_id == connection.id,
                IngestionDelivery.delivery_key == delivery_key,
            )
        )
        if found is None:
            raise AppError(409, "conflict", "Доставка уже создаётся") from exc
        if found.request_fingerprint != request_fingerprint:
            raise AppError(
                409,
                "delivery_conflict",
                "Другой состав доставки для того же transport-ключа",
            ) from exc
        return found
    return row


def get_or_create_part(
    session: Session,
    delivery: IngestionDelivery,
    *,
    part_index: int,
    content_hash: str,
    at: datetime,
) -> IngestionDeliveryPart:
    existing = session.scalar(
        select(IngestionDeliveryPart).where(
            IngestionDeliveryPart.tenant_id == delivery.tenant_id,
            IngestionDeliveryPart.delivery_id == delivery.id,
            IngestionDeliveryPart.part_index == part_index,
        )
    )
    if existing is not None:
        return existing
    row = IngestionDeliveryPart(
        id=uuid.uuid4(),
        tenant_id=delivery.tenant_id,
        delivery_id=delivery.id,
        company_id=delivery.company_id,
        connection_id=delivery.connection_id,
        part_index=part_index,
        content_hash=content_hash,
        batch_id=None,
        part_status=PART_PENDING,
        error_code=None,
        created_at=at,
        updated_at=at,
    )
    session.add(row)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        found = session.scalar(
            select(IngestionDeliveryPart).where(
                IngestionDeliveryPart.tenant_id == delivery.tenant_id,
                IngestionDeliveryPart.delivery_id == delivery.id,
                IngestionDeliveryPart.part_index == part_index,
            )
        )
        if found is None:
            raise AppError(409, "conflict", "Часть доставки уже создаётся") from exc
        return found
    return row


def link_part_to_batch(
    session: Session,
    part: IngestionDeliveryPart,
    batch: ImportBatch,
    *,
    part_status: str,
    error_code: str | None,
    at: datetime,
) -> None:
    if batch.tenant_id != part.tenant_id or batch.company_id != part.company_id:
        raise AppError(409, "forbidden", "Партия другой фирмы")
    if batch.connection_id != part.connection_id:
        raise AppError(409, "forbidden", "Партия другого источника")
    part.batch_id = batch.id
    part.part_status = part_status
    part.error_code = error_code
    part.updated_at = at
    session.flush()


def refresh_delivery_transport_status(
    session: Session, delivery_id: uuid.UUID, at: datetime
) -> None:
    delivery = session.get(IngestionDelivery, delivery_id)
    if delivery is None:
        return
    parts = session.scalars(
        select(IngestionDeliveryPart).where(
            IngestionDeliveryPart.tenant_id == delivery.tenant_id,
            IngestionDeliveryPart.delivery_id == delivery.id,
        )
    ).all()
    if not parts:
        delivery.transport_status = STATUS_REJECTED
    elif all(item.part_status == PART_PREVIEW for item in parts):
        delivery.transport_status = STATUS_COMPLETE
    elif any(item.part_status == PART_PREVIEW for item in parts):
        delivery.transport_status = STATUS_PARTIAL
    elif all(item.part_status in {PART_FAILED, PART_IGNORED} for item in parts):
        delivery.transport_status = STATUS_REJECTED
    else:
        delivery.transport_status = STATUS_PARTIAL
    delivery.updated_at = at
    session.flush()


def attach_delivery_id(payload: dict, delivery_id: uuid.UUID) -> dict:
    body = dict(payload)
    body["delivery_id"] = str(delivery_id)
    return body


def content_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def group_mail_attachments(
    messages: list[MailAttachment],
) -> dict[tuple[int, int], list[MailAttachment]]:
    grouped: dict[tuple[int, int], list[MailAttachment]] = {}
    for item in messages:
        key = (item.uidvalidity, item.uid)
        grouped.setdefault(key, []).append(item)
    for key in grouped:
        grouped[key].sort(key=lambda row: (row.filename, row.message_id))
    return grouped


def mail_manifest(
    connection_id: uuid.UUID, attachments: list[MailAttachment]
) -> tuple[str, list[tuple[int, str]]]:
    indexed: list[tuple[int, str]] = []
    for index, attachment in enumerate(attachments, start=1):
        indexed.append((index, content_digest(attachment.content)))
    return manifest_fingerprint(connection_id, indexed), indexed


SESSION_FINGERPRINT_VERSION = "1"


def session_delivery_key(user_id: uuid.UUID, delivery_key: str) -> str:
    return f"session-ingest:{user_id}:{delivery_key}"


def session_request_fingerprint(
    company_id: uuid.UUID,
    connection_id: uuid.UUID,
    manifest: list[tuple[int, str, str, str]],
) -> str:
    ordered = sorted(manifest, key=lambda item: item[0])
    body = ";".join(f"{idx}:{dataset}:{fmt}:{digest}" for idx, dataset, fmt, digest in ordered)
    raw = (
        f"{SESSION_FINGERPRINT_VERSION}:ui:{company_id}:{connection_id}:{body}"
    )
    return canonical_hash(raw)


def mark_part_failed(
    session: Session,
    part: IngestionDeliveryPart,
    error_code: str,
    at: datetime,
) -> None:
    part.part_status = PART_FAILED
    part.error_code = error_code
    part.updated_at = at
    session.flush()


def build_session_delivery_response(session: Session, delivery_id: uuid.UUID) -> dict:
    delivery = session.get(IngestionDelivery, delivery_id)
    if delivery is None:
        raise AppError(404, "not_found", "Доставка не найдена")
    parts = session.scalars(
        select(IngestionDeliveryPart)
        .where(
            IngestionDeliveryPart.tenant_id == delivery.tenant_id,
            IngestionDeliveryPart.delivery_id == delivery.id,
        )
        .order_by(IngestionDeliveryPart.part_index)
    ).all()
    part_payloads: list[dict] = []
    for item in parts:
        batch_status: str | None = None
        links: dict[str, str] | None = None
        batch_id: str | None = None
        if item.batch_id is not None:
            batch = session.get(ImportBatch, item.batch_id)
            batch_id = str(item.batch_id)
            if batch is not None:
                batch_status = batch.status
            links = {
                "preview": f"/api/v1/imports/{item.batch_id}/preview",
                "errors": f"/api/v1/imports/{item.batch_id}/errors",
            }
        part_payloads.append(
            {
                "part_index": item.part_index,
                "state": item.part_status,
                "error_code": item.error_code,
                "batch_id": batch_id,
                "batch_status": batch_status,
                "links": links,
            }
        )
    return {
        "delivery_id": str(delivery.id),
        "transport_status": delivery.transport_status,
        "parts": part_payloads,
    }
