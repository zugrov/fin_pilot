"""Локальный ingress: gate → существующий mail preview (FA-R04.2.1).

Не подключается к IMAP/poll/worker/HTTP. session.commit() не вызывает.
"""

from __future__ import annotations

from datetime import datetime

from app.config import Settings
from app.domain.mail_admission import MailAdmissionOutcome, UntrustedMailEnvelope
from app.domain.mail_ingress import (
    MailIngressResult,
    MailIngressStage,
    TrustedIngressBundle,
    bind_message_to_transport,
    check_raw_message_size,
    extract_attachments_from_raw,
    extract_envelope_from_raw,
    ingress_raw_byte_limit,
)
from app.errors import AppError
from app.integrations.imap_client import MailAttachment
from app.models.identity import Company, User
from app.models.imports import EmailIngestion, IngestionDelivery, SourceConnection
from app.security.access import require_membership
from app.security.context import set_context
from app.services import mail_service
from app.services.ingestion_delivery_service import mail_delivery_key
from app.services.mail_admission_service import evaluate_mail_admission
from app.services.mail_quarantine_service import record_mail_quarantine_for_ingress
from sqlalchemy import select
from sqlalchemy.orm import Session


def ingest_trusted_local_mail(
    session: Session,
    settings: Settings,
    *,
    raw_message: bytes,
    bundle: TrustedIngressBundle,
    at: datetime,
) -> MailIngressResult:
    envelope: UntrustedMailEnvelope | None = None
    attachments: list[MailAttachment] | None = None

    def finish(result: MailIngressResult) -> MailIngressResult:
        record_mail_quarantine_for_ingress(
            session,
            settings,
            raw_message=raw_message,
            bundle=bundle,
            result=result,
            at=at,
            envelope=envelope,
            attachments=attachments,
        )
        return result

    max_bytes = ingress_raw_byte_limit(settings)
    size_code = check_raw_message_size(raw_message, max_bytes)
    if size_code is not None:
        return finish(_reject(size_code, admission=None))

    mismatch = bind_message_to_transport(raw_message, bundle.message_digest)
    if mismatch is not None:
        return finish(_reject(mismatch, admission=None))

    envelope_or_error = extract_envelope_from_raw(raw_message)
    if isinstance(envelope_or_error, str):
        if envelope_or_error == "ambiguous_sender":
            return finish(
                MailIngressResult(
                    stage=MailIngressStage.REVIEW,
                    reason_code="ambiguous_sender",
                    admission=None,
                )
            )
        return finish(_reject(envelope_or_error, admission=None))

    envelope = envelope_or_error
    admission = evaluate_mail_admission(
        session,
        settings,
        envelope=envelope,
        transport=bundle.transport,
        binding=bundle.binding,
        at=at,
    )
    if admission.outcome == MailAdmissionOutcome.REJECT:
        return finish(
            MailIngressResult(
                stage=MailIngressStage.REJECTED,
                reason_code=admission.reason_code,
                admission=admission,
            )
        )
    if admission.outcome == MailAdmissionOutcome.REVIEW:
        return finish(
            MailIngressResult(
                stage=MailIngressStage.REVIEW,
                reason_code=admission.reason_code,
                admission=admission,
            )
        )
    if admission.context is None:
        return finish(_reject("admission_context_missing", admission=admission))

    ctx = admission.context
    if (
        ctx.tenant_id != bundle.binding.tenant_id
        or ctx.company_id != bundle.binding.company_id
        or ctx.connection_id != bundle.binding.connection_id
        or ctx.actor_user_id != bundle.binding.actor_user_id
    ):
        return finish(_reject("routing_binding_conflict", admission=admission))

    set_context(session, tenant_id=ctx.tenant_id, user_id=ctx.actor_user_id)
    connection = session.get(SourceConnection, bundle.binding.connection_id)
    if connection is None:
        return finish(_reject("source_not_found", admission=admission))
    if not connection.enabled or connection.status != "active":
        return finish(_reject("source_disabled", admission=admission))

    config_sender = str((connection.config_redacted or {}).get("sender") or "")
    attachments_or_error = extract_attachments_from_raw(
        raw_message,
        slot=bundle.delivery_slot,
        attachment_sender=config_sender,
    )
    if isinstance(attachments_or_error, str):
        return finish(_reject(attachments_or_error, admission=admission))

    attachments = attachments_or_error
    user = session.get(User, ctx.actor_user_id)
    company = session.get(Company, ctx.company_id)
    if user is None or company is None:
        return finish(_reject("not_found", admission=admission))

    membership = require_membership(session, user.id, ctx.tenant_id)
    try:
        touched = mail_service._ingest_message(
            session,
            settings,
            connection,
            membership,
            company,
            user,
            attachments,
            config_sender,
            at,
        )
    except AppError as exc:
        if exc.code == "delivery_conflict":
            return finish(
                MailIngressResult(
                    stage=MailIngressStage.REJECTED,
                    reason_code="delivery_conflict",
                    admission=admission,
                )
            )
        raise

    batch_ids = _preview_batch_ids(session, connection, bundle.delivery_slot)
    delivery_id = _delivery_id(session, connection, bundle.delivery_slot)
    return MailIngressResult(
        stage=MailIngressStage.PREVIEW,
        reason_code="ok",
        admission=admission,
        preview_created=touched,
        delivery_id=delivery_id,
        batch_ids=batch_ids,
    )


def _reject(reason_code: str, *, admission) -> MailIngressResult:
    return MailIngressResult(
        stage=MailIngressStage.REJECTED,
        reason_code=reason_code,
        admission=admission,
    )


def _delivery_id(session: Session, connection: SourceConnection, slot) -> str | None:
    key = mail_delivery_key(connection.id, slot.uidvalidity, slot.uid)
    delivery = session.scalar(
        select(IngestionDelivery).where(
            IngestionDelivery.tenant_id == connection.tenant_id,
            IngestionDelivery.connection_id == connection.id,
            IngestionDelivery.delivery_key == key,
        )
    )
    return None if delivery is None else str(delivery.id)


def _preview_batch_ids(session: Session, connection: SourceConnection, slot) -> tuple[str, ...]:
    rows = session.scalars(
        select(EmailIngestion.batch_id).where(
            EmailIngestion.tenant_id == connection.tenant_id,
            EmailIngestion.connection_id == connection.id,
            EmailIngestion.uidvalidity == slot.uidvalidity,
            EmailIngestion.uid == slot.uid,
            EmailIngestion.status == "preview",
            EmailIngestion.batch_id.is_not(None),
        )
    ).all()
    return tuple(str(item) for item in rows if item is not None)
