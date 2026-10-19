"""Session User Transport ingest (FA-R02.3)."""

from __future__ import annotations

import uuid
from datetime import datetime

from app.config import Settings
from app.errors import AppError
from app.models.identity import Company, IdempotencyRecord, Membership, User
from app.models.imports import IngestionDelivery, IngestionDeliveryPart, SourceConnection
from app.schemas.session_ingestion import (
    ParsedSessionEnvelope,
    SessionIngestPartMeta,
    parse_envelope_json,
)
from app.services import import_service
from app.services.dataset_coverage_service import record_completeness_claim
from app.services.delivery_validation_service import refresh_delivery_validation
from app.services.ingestion_delivery_service import (
    PART_PREVIEW,
    TransportContext,
    apply_session_envelope_to_delivery,
    build_session_delivery_response,
    content_digest,
    get_or_create_part,
    is_expected_unique_violation,
    mark_part_failed,
    refresh_delivery_transport_status,
    resolve_delivery,
    session_delivery_key,
    session_request_fingerprint,
)
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

SESSION_INGEST_SCOPE = "session-ingest"
IDEMPOTENCY_SCOPE_CONSTRAINT = frozenset({"idempotency_user_scope_key_uq"})

PART_ERROR_STATUS = frozenset({413, 422})
PART_ERROR_CODES = frozenset(
    {
        "validation_error",
        "unsupported_format",
        "payload_too_large",
    }
)

_DATASET_FORMATS: dict[str, frozenset[str]] = {
    "cash": frozenset({"csv", "xlsx", "clientbank"}),
    "revenue": frozenset({"csv"}),
    "plan": frozenset({"csv"}),
    "budget": frozenset({"csv"}),
    "balances": frozenset({"csv"}),
}


def require_session_ingest_enabled(settings: Settings) -> None:
    if not settings.session_ingest_enabled:
        raise AppError(404, "not_found", "Маршрут недоступен")


def reject_bearer_auth(request) -> None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        raise AppError(401, "unauthorized", "Bearer не поддерживается для session ingest")


def _session_ingest_lock(session: Session, user_id: uuid.UUID, delivery_key: str) -> None:
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"{SESSION_INGEST_SCOPE}:{user_id}:{delivery_key}"},
    )


def _replay_response(record: IdempotencyRecord) -> tuple[int, dict]:
    return 200, dict(record.response_body)


def _validate_connection_scope(
    session: Session, company: Company, connection_id: uuid.UUID
) -> SourceConnection:
    return import_service._connection(session, company, connection_id)  # noqa: SLF001


def _validate_parts_against_connection(
    envelope: ParsedSessionEnvelope, connection: SourceConnection
) -> None:
    indices = [item.part_index for item in envelope.parts]
    if len(indices) != len(set(indices)):
        raise AppError(422, "validation_error", "part_index должен быть уникален")
    expected = list(range(1, len(indices) + 1))
    if sorted(indices) != expected:
        raise AppError(422, "validation_error", "part_index должен быть 1..N без пропусков")
    for item in envelope.parts:
        if item.dataset != connection.dataset:
            raise AppError(422, "validation_error", "dataset части не совпадает с источником")
        allowed = _DATASET_FORMATS.get(connection.dataset, frozenset())
        if item.format not in allowed or item.format != connection.format:
            raise AppError(422, "validation_error", "format части не совпадает с источником")


def _idempotent(
    session: Session, user: User, key: str, request_hash: str
) -> IdempotencyRecord | None:
    row = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.scope == SESSION_INGEST_SCOPE,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if row is None:
        return None
    if row.request_hash != request_hash:
        raise AppError(409, "idempotency_conflict", "Другой состав для того же ключа")
    return row


def _remember(
    session: Session,
    user: User,
    tenant_id: uuid.UUID,
    key: str,
    request_hash: str,
    status_code: int,
    payload: dict,
    at: datetime,
) -> IdempotencyRecord | None:
    try:
        with session.begin_nested():
            session.add(
                IdempotencyRecord(
                    tenant_id=tenant_id,
                    user_id=user.id,
                    scope=SESSION_INGEST_SCOPE,
                    idempotency_key=key,
                    request_hash=request_hash,
                    status_code=status_code,
                    response_body=payload,
                    created_at=at,
                )
            )
            session.flush()
    except IntegrityError as exc:
        if not is_expected_unique_violation(exc, IDEMPOTENCY_SCOPE_CONSTRAINT):
            raise
        row = _idempotent(session, user, key, request_hash)
        if row is None:
            raise AppError(409, "conflict", "Ключ idempotency уже занят") from exc
        return row
    return None


def _is_expected_part_error(exc: AppError) -> bool:
    return exc.status_code in PART_ERROR_STATUS and exc.code in PART_ERROR_CODES


def _process_part(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    connection_id: uuid.UUID,
    part: IngestionDeliveryPart,
    content: bytes,
    delivery_key: str,
    at: datetime,
) -> None:
    if part.part_status == PART_PREVIEW and part.batch_id is not None:
        return
    transport = TransportContext(delivery_id=part.delivery_id, part_id=part.id)
    try:
        with session.begin_nested():
            import_service.receive_import(
                session,
                membership,
                company,
                user,
                settings,
                connection_id=connection_id,
                content=content,
                idempotency_key=f"{delivery_key}:part:{part.part_index}",
                at=at,
                transport=transport,
                skip_http_idempotency=True,
            )
    except AppError as exc:
        if not _is_expected_part_error(exc):
            raise
        mark_part_failed(session, part, exc.code, at)


def accept_session_ingestion(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    *,
    envelope_text: str,
    file_blobs: list[bytes],
    idempotency_header: str,
    at: datetime,
) -> tuple[int, dict]:
    import_service._deny(membership)  # noqa: SLF001
    import_service.open_company(session, user, company.id, settings, "write")

    if len(envelope_text.encode("utf-8")) > settings.session_ingest_max_envelope_bytes:
        raise AppError(413, "payload_too_large", "Envelope больше лимита")
    envelope = parse_envelope_json(envelope_text)
    if envelope.delivery_key != idempotency_header:
        raise AppError(422, "validation_error", "Idempotency-Key должен совпадать с delivery_key")
    if len(envelope.parts) > settings.session_ingest_max_parts:
        raise AppError(422, "validation_error", "Слишком много частей")
    if len(file_blobs) != len(envelope.parts):
        raise AppError(422, "validation_error", "Число файлов не совпадает с parts")

    connection = _validate_connection_scope(session, company, envelope.connection_id)
    _validate_parts_against_connection(envelope, connection)

    ordered_parts = sorted(envelope.parts, key=lambda item: item.part_index)
    manifest: list[tuple[int, str, str, str]] = []
    paired: list[tuple[SessionIngestPartMeta, bytes]] = []
    for index, meta in enumerate(ordered_parts):
        blob = file_blobs[index]
        digest = content_digest(blob)
        if digest != meta.content_sha256:
            raise AppError(422, "validation_error", "content_sha256 не совпадает с файлом")
        manifest.append((meta.part_index, meta.dataset, meta.format, digest))
        paired.append((meta, blob))

    fingerprint = session_request_fingerprint(
        company.id, connection.id, manifest, envelope=envelope
    )
    _session_ingest_lock(session, user.id, envelope.delivery_key)

    replay = _idempotent(session, user, envelope.delivery_key, fingerprint)
    if replay is not None:
        return _replay_response(replay)

    delivery = resolve_delivery(
        session,
        company,
        connection,
        channel="ui",
        delivery_key=session_delivery_key(user.id, envelope.delivery_key),
        request_fingerprint=fingerprint,
        at=at,
    )
    apply_session_envelope_to_delivery(session, delivery, envelope, company, at)

    replay = _idempotent(session, user, envelope.delivery_key, fingerprint)
    if replay is not None:
        return _replay_response(replay)

    for meta, blob in paired:
        part = get_or_create_part(
            session,
            delivery,
            part_index=meta.part_index,
            content_hash=meta.content_sha256,
            at=at,
        )
        _process_part(
            session,
            membership,
            company,
            user,
            settings,
            connection.id,
            part,
            blob,
            envelope.delivery_key,
            at,
        )

    refresh_delivery_transport_status(session, delivery.id, at)
    refresh_delivery_validation(session, delivery, connection, at)
    record_completeness_claim(
        session,
        delivery,
        connection,
        company,
        envelope.completeness_claim,
        at,
    )
    body = build_session_delivery_response(session, delivery.id)
    duplicate = _remember(
        session,
        user,
        company.tenant_id,
        envelope.delivery_key,
        fingerprint,
        201,
        body,
        at,
    )
    if duplicate is not None:
        return _replay_response(duplicate)
    return 201, body


def get_session_delivery(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    delivery_id: uuid.UUID,
) -> dict:
    import_service._deny(membership)  # noqa: SLF001
    delivery = session.get(IngestionDelivery, delivery_id)
    if delivery is None or delivery.tenant_id != membership.tenant_id:
        raise AppError(404, "not_found", "Доставка не найдена")
    import_service.open_company(session, user, delivery.company_id, settings, "read")
    return build_session_delivery_response(session, delivery_id)
