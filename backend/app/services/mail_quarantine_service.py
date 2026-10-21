"""Запись карантина из ingress и retention-функция (FA-R04.2.3)."""

from __future__ import annotations

import json
from datetime import datetime
from email import message_from_bytes
from email.errors import MessageParseError

from app.config import Settings
from app.domain.mail_admission import UntrustedMailEnvelope
from app.domain.mail_ingress import MailIngressResult, MailIngressStage, TrustedIngressBundle
from app.domain.mail_quarantine import (
    admission_outcome_for_result,
    build_metadata_allowed,
    retain_until_for_outcome,
    sender_domain_from_envelope,
    sender_normalized_for_record,
)
from app.errors import AppError
from app.integrations.imap_client import MailAttachment
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session


def record_mail_quarantine_for_ingress(
    session: Session,
    settings: Settings,
    *,
    raw_message: bytes,
    bundle: TrustedIngressBundle,
    result: MailIngressResult,
    at: datetime,
    envelope: UntrustedMailEnvelope | None = None,
    attachments: list[MailAttachment] | None = None,
) -> None:
    if not settings.mail_quarantine_enabled:
        return
    if result.stage not in (MailIngressStage.REJECTED, MailIngressStage.REVIEW):
        return

    admission_outcome = admission_outcome_for_result(result)
    metadata = build_metadata_allowed(
        reason_code=result.reason_code,
        stage=result.stage,
        sender_domain=sender_domain_from_envelope(envelope),
        attachments=attachments,
    )
    sender_normalized = sender_normalized_for_record(result, result.admission, envelope)
    retain_until = retain_until_for_outcome(
        at=at,
        outcome=admission_outcome,
        reject_ttl_days=settings.mail_quarantine_reject_ttl_days,
        review_ttl_days=settings.mail_quarantine_review_ttl_days,
    )
    try:
        session.execute(
            text(
                """
                SELECT app_record_mail_quarantine(
                  :tenant_id,
                  :company_id,
                  :connection_id,
                  :uidvalidity,
                  :uid,
                  :message_digest,
                  :message_id_header,
                  :ingress_stage,
                  :reason_code,
                  :admission_outcome,
                  :sender_normalized,
                  CAST(:metadata_allowed AS jsonb),
                  :transport_trust_level,
                  :daily_limit,
                  :at,
                  :retain_until
                )
                """
            ),
            {
                "tenant_id": bundle.binding.tenant_id,
                "company_id": bundle.binding.company_id,
                "connection_id": bundle.binding.connection_id,
                "uidvalidity": bundle.delivery_slot.uidvalidity,
                "uid": bundle.delivery_slot.uid,
                "message_digest": bundle.message_digest,
                "message_id_header": _extract_message_id_header(raw_message),
                "ingress_stage": result.stage.value,
                "reason_code": result.reason_code,
                "admission_outcome": admission_outcome,
                "sender_normalized": sender_normalized,
                "metadata_allowed": json.dumps(metadata, ensure_ascii=False),
                "transport_trust_level": "fixture",
                "daily_limit": settings.mail_quarantine_daily_entry_limit,
                "at": at,
                "retain_until": retain_until,
            },
        )
    except SQLAlchemyError as exc:
        raise AppError(
            500,
            "mail_quarantine_write_failed",
            "Не удалось записать карантин входящей почты",
            details={"reason": str(exc.__cause__ or exc)},
        ) from exc


def expire_mail_quarantine_entries(
    session: Session,
    *,
    before: datetime,
    limit: int,
) -> int:
    row = session.execute(
        text("SELECT app_expire_mail_quarantine_entries(:before, :limit)"),
        {"before": before, "limit": limit},
    ).scalar_one()
    return int(row)


def _extract_message_id_header(raw_message: bytes) -> str | None:
    try:
        message = message_from_bytes(raw_message)
    except (MessageParseError, TypeError, ValueError):
        return None
    value = message.get("Message-ID")
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None
