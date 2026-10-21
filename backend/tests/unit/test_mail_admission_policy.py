from uuid import uuid4

from app.domain.mail_admission import (
    MailAdmissionOutcome,
    TrustedServerBinding,
    TrustedTransportAuth,
    UntrustedMailEnvelope,
    apply_mail_admission_policy,
    parse_from_header,
    reject_sender_identity_mismatch,
)
from app.services.auth_service import normalize_email


def _trusted(**overrides: object) -> TrustedTransportAuth:
    base = dict(
        message_authenticated=True,
        spf="pass",
        dkim="pass",
        dmarc="pass",
    )
    base.update(overrides)
    return TrustedTransportAuth(**base)  # type: ignore[arg-type]


def test_trusted_single_from_proceeds() -> None:
    envelope = UntrustedMailEnvelope(from_header="Pilot <pilot@example.com>")
    result = apply_mail_admission_policy(envelope, _trusted())
    assert result.sender_normalized == "pilot@example.com"
    assert reject_sender_identity_mismatch("pilot@example.com", "pilot@example.com") is None


def test_missing_transport_evidence_rejects() -> None:
    envelope = UntrustedMailEnvelope(from_header="pilot@example.com")
    stop = apply_mail_admission_policy(envelope, None)
    assert stop.decision.outcome == MailAdmissionOutcome.REJECT
    assert stop.decision.reason_code == "transport_evidence_missing"


def test_forged_authentication_results_rejects() -> None:
    envelope = UntrustedMailEnvelope(
        from_header="pilot@example.com",
        authentication_results_header="mx.example.com; spf=pass smtp.mailfrom=evil.test",
    )
    transport = _trusted(message_authenticated=False, spf="fail", dkim="fail", dmarc="fail")
    stop = apply_mail_admission_policy(envelope, transport)
    assert stop.decision.reason_code == "forged_authentication_results"


def test_ambiguous_multiple_from_is_review() -> None:
    envelope = UntrustedMailEnvelope(
        from_header="One <a@example.com>, Two <b@example.com>",
    )
    stop = apply_mail_admission_policy(envelope, _trusted())
    assert stop.decision.outcome == MailAdmissionOutcome.REVIEW
    assert stop.decision.reason_code == "ambiguous_sender"


def test_display_name_does_not_grant_access() -> None:
    envelope = UntrustedMailEnvelope(
        from_header='"Директор" <intruder@example.com>',
    )
    proceed = apply_mail_admission_policy(envelope, _trusted())
    stop = reject_sender_identity_mismatch(proceed.sender_normalized, "pilot@example.com")
    assert stop is not None
    assert stop.decision.reason_code == "sender_not_verified_user"


def test_reply_to_does_not_grant_access() -> None:
    envelope = UntrustedMailEnvelope(
        from_header="intruder@example.com",
        reply_to_header="Pilot User <pilot@example.com>",
    )
    proceed = apply_mail_admission_policy(envelope, _trusted())
    stop = reject_sender_identity_mismatch(proceed.sender_normalized, "pilot@example.com")
    assert stop is not None
    assert stop.decision.reason_code == "sender_not_verified_user"


def test_email_aliases_are_not_merged() -> None:
    registered = "pilot@gmail.com"
    plus_alias = "pilot+tag@gmail.com"
    assert normalize_email(plus_alias) != normalize_email(registered)
    envelope = UntrustedMailEnvelope(from_header=plus_alias)
    proceed = apply_mail_admission_policy(envelope, _trusted())
    stop = reject_sender_identity_mismatch(proceed.sender_normalized, registered)
    assert stop is not None
    assert stop.decision.reason_code == "sender_not_verified_user"


def test_parse_from_header_single_mailbox() -> None:
    parsed = parse_from_header("Pilot Example <pilot@example.com>")
    assert len(parsed) == 1
    assert parsed[0].addr_spec == "pilot@example.com"


def test_binding_dataclass_is_inert() -> None:
    binding = TrustedServerBinding(
        connection_id=uuid4(),
        tenant_id=uuid4(),
        company_id=uuid4(),
        actor_user_id=uuid4(),
    )
    assert binding.connection_id is not None
