"""Локальный ingress письма: разбор заголовков и лимиты до gate (FA-R04.2.1)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from email import message_from_bytes
from email.errors import MessageParseError
from enum import StrEnum

from app.domain.mail_admission import (
    MailAdmissionDecision,
    TrustedServerBinding,
    TrustedTransportAuth,
    UntrustedMailEnvelope,
    parse_from_header,
)
from app.integrations.imap_client import MailAttachment


class MailIngressStage(StrEnum):
    REJECTED = "rejected"
    REVIEW = "review"
    PREVIEW = "preview"


@dataclass(frozen=True)
class MailDeliverySlot:
    """Transport-ключ доставки (не Message-ID)."""

    uidvalidity: int
    uid: int
    folder: str = "INBOX"


@dataclass(frozen=True)
class TrustedIngressBundle:
    """Доверенный контекст ingress: fixture, не из тела письма."""

    transport: TrustedTransportAuth
    binding: TrustedServerBinding
    delivery_slot: MailDeliverySlot
    message_digest: str


@dataclass(frozen=True)
class MailIngressResult:
    stage: MailIngressStage
    reason_code: str
    admission: MailAdmissionDecision | None = None
    preview_created: bool = False
    delivery_id: str | None = None
    batch_ids: tuple[str, ...] = ()


def raw_message_digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def ingress_raw_byte_limit(settings) -> int:
    return int(settings.import_max_bytes)


def check_raw_message_size(raw: bytes, max_bytes: int) -> str | None:
    if len(raw) > max_bytes:
        return "message_too_large"
    if not raw.strip():
        return "message_empty"
    return None


def bind_message_to_transport(raw: bytes, expected_digest: str) -> str | None:
    actual = raw_message_digest(raw)
    if actual != expected_digest:
        return "message_transport_mismatch"
    return None


def extract_envelope_from_raw(raw: bytes) -> UntrustedMailEnvelope | str:
    try:
        message = message_from_bytes(raw)
    except (MessageParseError, TypeError, ValueError):
        return "mime_invalid"
    from_header = message.get("From", "") or ""
    if not from_header.strip():
        return "sender_missing"
    from_addrs = parse_from_header(from_header)
    if len(from_addrs) > 1:
        return "ambiguous_sender"
    return UntrustedMailEnvelope(
        from_header=from_header,
        reply_to_header=message.get("Reply-To"),
        authentication_results_header=message.get("Authentication-Results"),
    )


def extract_attachments_from_raw(
    raw: bytes,
    *,
    slot: MailDeliverySlot,
    attachment_sender: str,
) -> list[MailAttachment] | str:
    try:
        message = message_from_bytes(raw)
    except (MessageParseError, TypeError, ValueError):
        return "mime_invalid"
    message_id = message.get("Message-ID", "") or ""
    found: list[MailAttachment] = []
    for part in message.walk():
        if part.get_content_disposition() != "attachment":
            continue
        filename = part.get_filename() or "attachment"
        if ".." in filename or filename.startswith("/"):
            return "unsafe_attachment_name"
        payload = part.get_payload(decode=True)
        content = payload if isinstance(payload, bytes) else b""
        found.append(
            MailAttachment(
                uidvalidity=slot.uidvalidity,
                uid=slot.uid,
                message_id=message_id,
                sender=attachment_sender,
                folder=slot.folder,
                filename=filename,
                content=content,
            )
        )
    if not found:
        return "attachment_missing"
    return found


def build_simple_mime(
    *,
    from_addr: str,
    attachment_name: str,
    attachment_bytes: bytes,
    message_id: str | None = None,
) -> bytes:
    boundary = "finpilot-ingress-boundary"
    mid = message_id or "<ingress-test@local>"
    head = (
        f"From: {from_addr}\r\n"
        f"Message-ID: {mid}\r\n"
        f"MIME-Version: 1.0\r\n"
        f'Content-Type: multipart/mixed; boundary="{boundary}"\r\n'
        "\r\n"
        f"--{boundary}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "synthetic ingress fixture\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: attachment; filename="{attachment_name}"\r\n'
        "Content-Transfer-Encoding: binary\r\n"
        "\r\n"
    ).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return head + attachment_bytes + tail
