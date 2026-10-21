from uuid import uuid4

from app.config import Settings
from app.domain.mail_admission import (
    TrustedServerBinding,
    TrustedTransportAuth,
)
from app.domain.mail_ingress import (
    MailDeliverySlot,
    TrustedIngressBundle,
    bind_message_to_transport,
    build_simple_mime,
    check_raw_message_size,
    extract_envelope_from_raw,
    raw_message_digest,
)


def _trusted() -> TrustedTransportAuth:
    return TrustedTransportAuth(
        message_authenticated=True,
        spf="pass",
        dkim="pass",
        dmarc="pass",
    )


def test_valid_message_digest_binding() -> None:
    raw = build_simple_mime(
        from_addr="user@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"1CClientBankExchange\n",
    )
    digest = raw_message_digest(raw)
    assert bind_message_to_transport(raw, digest) is None
    assert bind_message_to_transport(raw, "deadbeef") == "message_transport_mismatch"


def test_oversized_message_rejected() -> None:
    raw = b"x" * 11
    assert check_raw_message_size(raw, 10) == "message_too_large"


def test_ambiguous_from_in_raw_mime() -> None:
    raw = (
        b"From: a@example.com, b@example.com\r\n"
        b"Content-Type: text/plain\r\n\r\n"
        b"body"
    )
    assert extract_envelope_from_raw(raw) == "ambiguous_sender"


def test_missing_from_header_rejected() -> None:
    raw = b"Content-Type: text/plain; charset=utf-8\r\n\r\nno from header"
    assert extract_envelope_from_raw(raw) == "sender_missing"


def test_bundle_requires_explicit_digest() -> None:
    raw = b"From: u@example.com\r\n\r\nx"
    bundle = TrustedIngressBundle(
        transport=_trusted(),
        binding=TrustedServerBinding(
            connection_id=uuid4(),
            tenant_id=uuid4(),
            company_id=uuid4(),
            actor_user_id=uuid4(),
        ),
        delivery_slot=MailDeliverySlot(uidvalidity=1, uid=2),
        message_digest=raw_message_digest(raw),
    )
    assert bundle.message_digest == raw_message_digest(raw)


def test_transport_context_does_not_match_swapped_body() -> None:
    first = build_simple_mime(
        from_addr="user@example.com",
        attachment_name="a.txt",
        attachment_bytes=b"one",
    )
    second = build_simple_mime(
        from_addr="user@example.com",
        attachment_name="a.txt",
        attachment_bytes=b"two",
    )
    bundle = TrustedIngressBundle(
        transport=_trusted(),
        binding=TrustedServerBinding(
            connection_id=uuid4(),
            tenant_id=uuid4(),
            company_id=uuid4(),
            actor_user_id=uuid4(),
        ),
        delivery_slot=MailDeliverySlot(uidvalidity=9, uid=1),
        message_digest=raw_message_digest(first),
    )
    assert bind_message_to_transport(second, bundle.message_digest) == "message_transport_mismatch"


def test_ingress_byte_limit_uses_import_max_bytes() -> None:
    settings = Settings(app_env="test", import_max_bytes=2048)
    assert check_raw_message_size(b"a" * 2049, settings.import_max_bytes) == "message_too_large"
