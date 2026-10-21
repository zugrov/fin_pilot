from datetime import UTC, datetime

from app.domain.mail_admission import UntrustedMailEnvelope
from app.domain.mail_ingress import MailIngressStage
from app.domain.mail_quarantine import (
    MailQuarantineStatus,
    build_metadata_allowed,
    can_transition_status,
    immutable_fields_unchanged,
    metadata_keys_allowed,
    retain_until_for_outcome,
    sender_domain_from_envelope,
)
from app.integrations.imap_client import MailAttachment


def test_status_transitions_allow_open_to_closed_and_expired() -> None:
    assert can_transition_status(MailQuarantineStatus.OPEN, MailQuarantineStatus.CLOSED)
    assert can_transition_status(MailQuarantineStatus.OPEN, MailQuarantineStatus.EXPIRED)
    assert not can_transition_status(MailQuarantineStatus.EXPIRED, MailQuarantineStatus.OPEN)


def test_metadata_allowlist_rejects_forbidden_keys() -> None:
    assert metadata_keys_allowed({"reason_code": "x", "stage": "rejected"})
    assert not metadata_keys_allowed({"subject": "secret"})


def test_build_metadata_allowlist_has_no_subject_or_filenames() -> None:
    meta = build_metadata_allowed(
        reason_code="sender_not_verified_user",
        stage=MailIngressStage.REJECTED,
        sender_domain="example.com",
        attachments=[
            MailAttachment(
                uidvalidity=1,
                uid=1,
                message_id="<m@local>",
                sender="bank@example.com",
                folder="INBOX",
                filename="secret-statement.txt",
                content=b"x" * 12,
            )
        ],
    )
    assert "subject" not in meta
    assert "secret-statement.txt" not in str(meta)
    assert meta["extensions"] == ["txt"]
    assert meta["attachment_count"] == 1


def test_sender_domain_from_envelope() -> None:
    domain = sender_domain_from_envelope(
        UntrustedMailEnvelope(from_header="Pilot <pilot@bank.example>")
    )
    assert domain == "bank.example"


def test_retain_until_differs_for_review() -> None:
    at = datetime(2026, 10, 21, tzinfo=UTC)
    reject_until = retain_until_for_outcome(
        at=at,
        outcome="reject",
        reject_ttl_days=90,
        review_ttl_days=180,
    )
    review_until = retain_until_for_outcome(
        at=at,
        outcome="review",
        reject_ttl_days=90,
        review_ttl_days=180,
    )
    assert (review_until - at).days == 180
    assert (reject_until - at).days == 90


def test_immutable_fields_helper() -> None:
    assert immutable_fields_unchanged(
        reason_code="a",
        ingress_stage="rejected",
        admission_outcome="reject",
        new_reason_code="a",
        new_ingress_stage="rejected",
        new_admission_outcome="reject",
    )
    assert not immutable_fields_unchanged(
        reason_code="a",
        ingress_stage="rejected",
        admission_outcome="reject",
        new_reason_code="b",
        new_ingress_stage="rejected",
        new_admission_outcome="reject",
    )
