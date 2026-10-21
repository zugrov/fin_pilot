"""HTTP API карантина почты (FA-R04.3.1)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime

from app.config import Settings
from app.domain.mail_quarantine import MailQuarantineResolution, MailQuarantineStatus
from app.errors import AppError
from app.models.identity import AuditLog, Company, IdempotencyRecord, Membership, User
from app.models.mail_quarantine import MailQuarantineEntry
from app.security.access import (
    assert_finance_access,
    find_company_across_memberships,
    load_company,
)
from app.security.context import set_context
from app.security.tokens import canonical_hash
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

CLOSE_SCOPE = "mail_quarantine_close"
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_LIMIT = 50
_DIGEST_PREFIX_LEN = 16
_HTML_RE = re.compile(r"[<>]")


def require_quarantine_api(settings: Settings) -> None:
    if not settings.mail_quarantine_enabled:
        raise AppError(404, "not_found", "Не найдено")


def entry_payload(entry: MailQuarantineEntry) -> dict:
    digest = entry.message_digest or ""
    prefix = digest[:_DIGEST_PREFIX_LEN]
    if len(digest) > _DIGEST_PREFIX_LEN:
        prefix = f"{prefix}…"
    return {
        "id": str(entry.id),
        "connection_id": str(entry.connection_id),
        "uidvalidity": entry.uidvalidity,
        "uid": entry.uid,
        "ingress_stage": entry.ingress_stage,
        "reason_code": entry.reason_code,
        "admission_outcome": entry.admission_outcome,
        "status": entry.status,
        "resolution": entry.resolution,
        "resolution_note": entry.resolution_note,
        "metadata_allowed": dict(entry.metadata_allowed or {}),
        "slot_content_anomaly": entry.slot_content_anomaly,
        "message_digest_prefix": prefix,
        "created_at": entry.created_at.isoformat(),
        "resolved_at": None if entry.resolved_at is None else entry.resolved_at.isoformat(),
        "retain_until": entry.retain_until.isoformat(),
    }


def list_entries(
    session: Session,
    settings: Settings,
    *,
    membership: Membership,
    company: Company,
    status: str | None,
    limit: int,
    offset: int,
) -> list[MailQuarantineEntry]:
    require_quarantine_api(settings)
    if limit < 1 or limit > MAX_PAGE_LIMIT or offset < 0:
        raise AppError(422, "validation_error", "Некорректная страница")
    if status is not None and status not in {
        MailQuarantineStatus.OPEN.value,
        MailQuarantineStatus.CLOSED.value,
        MailQuarantineStatus.EXPIRED.value,
    }:
        raise AppError(422, "validation_error", "Неизвестный статус")
    query = (
        select(MailQuarantineEntry)
        .where(
            MailQuarantineEntry.tenant_id == company.tenant_id,
            MailQuarantineEntry.company_id == company.id,
        )
        .order_by(MailQuarantineEntry.created_at.desc(), MailQuarantineEntry.id.desc())
        .offset(offset)
        .limit(limit)
    )
    if status is not None:
        query = query.where(MailQuarantineEntry.status == status)
    return list(session.scalars(query).all())


def get_entry(
    session: Session,
    settings: Settings,
    *,
    membership: Membership,
    company: Company,
    entry_id: uuid.UUID,
) -> MailQuarantineEntry:
    require_quarantine_api(settings)
    entry = session.scalar(
        select(MailQuarantineEntry).where(
            MailQuarantineEntry.id == entry_id,
            MailQuarantineEntry.tenant_id == company.tenant_id,
            MailQuarantineEntry.company_id == company.id,
        )
    )
    if entry is None:
        raise AppError(404, "not_found", "Запись не найдена")
    return entry


def _close_request_hash(entry_id: uuid.UUID, resolution: str, note: str) -> str:
    body = {"entry_id": str(entry_id), "note": note, "resolution": resolution}
    return canonical_hash(json.dumps(body, sort_keys=True, separators=(",", ":")))


def _validate_close_note(note: str) -> str:
    cleaned = note.strip()
    if len(cleaned) > 500:
        raise AppError(422, "validation_error", "Комментарий слишком длинный")
    if _HTML_RE.search(cleaned):
        raise AppError(422, "validation_error", "Комментарий не должен содержать разметку")
    return cleaned


def _validate_resolution(raw: str) -> str:
    if raw not in (
        MailQuarantineResolution.DISMISSED.value,
        MailQuarantineResolution.ESCALATED.value,
    ):
        raise AppError(422, "validation_error", "Неизвестное решение")
    return raw


def _idempotent_close(
    session: Session,
    user: User,
    key: str,
    request_hash: str,
) -> dict | None:
    row = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.scope == CLOSE_SCOPE,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if row is None:
        return None
    if row.request_hash != request_hash:
        raise AppError(409, "idempotency_conflict", "Другой payload для того же ключа")
    return dict(row.response_body)


def _remember_close(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    user: User,
    key: str,
    request_hash: str,
    payload: dict,
    at: datetime,
) -> None:
    session.add(
        IdempotencyRecord(
            tenant_id=tenant_id,
            user_id=user.id,
            scope=CLOSE_SCOPE,
            idempotency_key=key,
            request_hash=request_hash,
            status_code=200,
            response_body=payload,
            created_at=at,
        )
    )


def close_entry(
    session: Session,
    settings: Settings,
    *,
    user: User,
    company: Company,
    entry_id: uuid.UUID,
    resolution: str,
    note: str,
    idempotency_key: str,
    at: datetime,
) -> dict:
    require_quarantine_api(settings)
    resolution = _validate_resolution(resolution)
    note = _validate_close_note(note)
    request_hash = _close_request_hash(entry_id, resolution, note)
    replay = _idempotent_close(session, user, idempotency_key, request_hash)
    if replay is not None:
        return replay

    entry = session.scalar(
        select(MailQuarantineEntry)
        .where(
            MailQuarantineEntry.id == entry_id,
            MailQuarantineEntry.tenant_id == company.tenant_id,
            MailQuarantineEntry.company_id == company.id,
        )
        .with_for_update()
    )
    if entry is None:
        raise AppError(404, "not_found", "Запись не найдена")
    if entry.status == MailQuarantineStatus.EXPIRED.value:
        raise AppError(409, "conflict", "Срок хранения записи истёк")
    if entry.status != MailQuarantineStatus.OPEN.value:
        raise AppError(409, "conflict", "Запись уже закрыта")

    session.execute(text("SELECT set_config('app.mail_quarantine_internal', '1', true)"))
    entry.status = MailQuarantineStatus.CLOSED.value
    entry.resolution = resolution
    entry.resolution_note = note or None
    entry.reviewer_user_id = user.id
    entry.resolved_at = at
    session.flush()

    session.add(
        AuditLog(
            tenant_id=company.tenant_id,
            user_id=user.id,
            action="mail_quarantine_resolved",
            entity_type="mail_quarantine_entry",
            entity_id=entry.id,
            before_redacted=None,
            after_redacted={"resolution": resolution, "entry_id": str(entry.id)},
            request_id=None,
            created_at=at,
        )
    )
    payload = {"entry": entry_payload(entry)}
    try:
        with session.begin_nested():
            _remember_close(
                session,
                tenant_id=company.tenant_id,
                user=user,
                key=idempotency_key,
                request_hash=request_hash,
                payload=payload,
                at=at,
            )
            session.flush()
    except IntegrityError:
        replay = _idempotent_close(session, user, idempotency_key, request_hash)
        if replay is None:
            raise
        return replay
    return payload


def open_for_read(
    session: Session,
    user: User,
    company_id: uuid.UUID,
    settings: Settings,
) -> tuple[Membership, Company]:
    membership, company = find_company_across_memberships(session, user.id, company_id)
    set_context(session, tenant_id=membership.tenant_id, user_id=user.id)
    company = load_company(session, membership, company_id)
    assert_finance_access(
        session,
        membership=membership,
        company=company,
        user_verified=user.email_verified_at is not None,
        at=_now(),
        mode="read",
        grace_days=settings.billing_grace_days,
        bypass=False,
    )
    return membership, company


def open_for_write(
    session: Session,
    user: User,
    company_id: uuid.UUID,
    settings: Settings,
) -> tuple[Membership, Company]:
    membership, company = find_company_across_memberships(session, user.id, company_id)
    set_context(session, tenant_id=membership.tenant_id, user_id=user.id)
    company = load_company(session, membership, company_id)
    assert_finance_access(
        session,
        membership=membership,
        company=company,
        user_verified=user.email_verified_at is not None,
        at=_now(),
        mode="write",
        grace_days=settings.billing_grace_days,
        bypass=False,
    )
    return membership, company


def _now() -> datetime:
    from app.clock import now

    return now()
