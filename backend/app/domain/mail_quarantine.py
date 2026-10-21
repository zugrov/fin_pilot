"""Постоянный карантин отказов/review на ingress (FA-R04.2.3)."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from app.domain.mail_admission import (
    MailAdmissionDecision,
    MailAdmissionOutcome,
    UntrustedMailEnvelope,
    parse_from_header,
)
from app.domain.mail_ingress import MailIngressResult, MailIngressStage
from app.integrations.imap_client import MailAttachment
from app.services.auth_service import normalize_email

_METADATA_ALLOWLIST = frozenset(
    {
        "reason_code",
        "stage",
        "sender_domain",
        "attachment_count",
        "attachment_total_bytes",
        "content_types",
        "extensions",
    }
)

_EXTENSION_RE = re.compile(r"\.([a-z0-9]{1,16})$", re.IGNORECASE)


class MailQuarantineStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"
    EXPIRED = "expired"


class MailQuarantineResolution(StrEnum):
    DISMISSED = "dismissed"
    ESCALATED = "escalated"


_ALLOWED_STATUS_TRANSITIONS: Mapping[
    MailQuarantineStatus, frozenset[MailQuarantineStatus]
] = {
    MailQuarantineStatus.OPEN: frozenset(
        {MailQuarantineStatus.CLOSED, MailQuarantineStatus.EXPIRED}
    ),
    MailQuarantineStatus.CLOSED: frozenset({MailQuarantineStatus.EXPIRED}),
    MailQuarantineStatus.EXPIRED: frozenset(),
}


def can_transition_status(
    current: MailQuarantineStatus,
    new: MailQuarantineStatus,
) -> bool:
    return new in _ALLOWED_STATUS_TRANSITIONS.get(current, frozenset())


def metadata_keys_allowed(payload: Mapping[str, Any]) -> bool:
    return all(key in _METADATA_ALLOWLIST for key in payload)


def sender_domain_from_envelope(envelope: UntrustedMailEnvelope | None) -> str | None:
    if envelope is None:
        return None
    addresses = parse_from_header(envelope.from_header)
    if len(addresses) != 1:
        return None
    normalized = normalize_email(addresses[0].addr_spec)
    if "@" not in normalized:
        return None
    return normalized.split("@", 1)[1]


def _content_type_guess(filename: str) -> str:
    ext = _extension_from_filename(filename)
    if ext == "txt":
        return "text/plain"
    if ext == "csv":
        return "text/csv"
    return "application/octet-stream"


def _extension_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    base = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    match = _EXTENSION_RE.search(base)
    if match is None:
        return None
    return match.group(1).lower()


def build_metadata_allowed(
    *,
    reason_code: str,
    stage: MailIngressStage,
    sender_domain: str | None,
    attachments: Sequence[MailAttachment] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "reason_code": reason_code,
        "stage": stage.value,
    }
    if sender_domain:
        payload["sender_domain"] = sender_domain[:253]
    items = attachments or ()
    if items:
        total_bytes = sum(len(item.content) for item in items)
        content_types = sorted({_content_type_guess(item.filename) for item in items})
        extensions = sorted(
            {
                ext
                for item in items
                if (ext := _extension_from_filename(item.filename)) is not None
            }
        )
        payload["attachment_count"] = len(items)
        payload["attachment_total_bytes"] = total_bytes
        if content_types:
            payload["content_types"] = content_types
        if extensions:
            payload["extensions"] = extensions
    if not metadata_keys_allowed(payload):
        raise ValueError("metadata вне allowlist")
    return payload


def admission_outcome_for_result(result: MailIngressResult) -> str:
    if result.stage == MailIngressStage.REVIEW:
        return "review"
    return "reject"


def sender_normalized_for_record(
    result: MailIngressResult,
    admission: MailAdmissionDecision | None,
    envelope: UntrustedMailEnvelope | None,
) -> str | None:
    if result.stage != MailIngressStage.REVIEW:
        return None
    if admission is not None and admission.context is not None:
        return admission.context.sender_normalized
    if envelope is None:
        return None
    addresses = parse_from_header(envelope.from_header)
    if len(addresses) != 1:
        return None
    normalized = normalize_email(addresses[0].addr_spec)
    return normalized or None


def retain_until_for_outcome(
    *,
    at: datetime,
    outcome: str,
    reject_ttl_days: int,
    review_ttl_days: int,
) -> datetime:
    base = at if at.tzinfo is not None else at.replace(tzinfo=UTC)
    if outcome == MailAdmissionOutcome.REVIEW.value or outcome == "review":
        delta = timedelta(days=review_ttl_days)
    else:
        delta = timedelta(days=reject_ttl_days)
    return base + delta


def immutable_fields_unchanged(
    *,
    reason_code: str,
    ingress_stage: str,
    admission_outcome: str,
    new_reason_code: str,
    new_ingress_stage: str,
    new_admission_outcome: str,
) -> bool:
    return (
        reason_code == new_reason_code
        and ingress_stage == new_ingress_stage
        and admission_outcome == new_admission_outcome
    )
