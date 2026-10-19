from app.domain.imports.revision import evaluate_revision


def test_numeric_revision_order() -> None:
    stale = evaluate_revision(
        incoming_revision=2,
        incoming_hash="a",
        applied_revision=10,
        applied_hash="b",
        identity_exists=True,
        at_commit=True,
    )
    assert stale is not None
    assert stale.error_code == "stale_revision"

    newer = evaluate_revision(
        incoming_revision=10,
        incoming_hash="b",
        applied_revision=2,
        applied_hash="a",
        identity_exists=True,
        at_commit=False,
    )
    assert newer is not None
    assert newer.action == "revise"


def test_equal_revision_different_payload() -> None:
    outcome = evaluate_revision(
        incoming_revision=5,
        incoming_hash="new",
        applied_revision=5,
        applied_hash="old",
        identity_exists=True,
        at_commit=True,
    )
    assert outcome is not None
    assert outcome.error_code == "revision_payload_conflict"


def test_higher_revision_same_payload_watermark_only() -> None:
    outcome = evaluate_revision(
        incoming_revision=7,
        incoming_hash="same",
        applied_revision=3,
        applied_hash="same",
        identity_exists=True,
        at_commit=False,
    )
    assert outcome is not None
    assert outcome.action == "skip"
    assert outcome.advance_watermark_only is True


def test_legacy_to_versioned_same_payload() -> None:
    outcome = evaluate_revision(
        incoming_revision=1,
        incoming_hash="h",
        applied_revision=None,
        applied_hash="h",
        identity_exists=True,
        at_commit=False,
    )
    assert outcome is not None
    assert outcome.action == "skip"
    assert outcome.advance_watermark_only is True


def test_versioned_identity_requires_revision_on_change() -> None:
    outcome = evaluate_revision(
        incoming_revision=None,
        incoming_hash="new",
        applied_revision=4,
        applied_hash="old",
        identity_exists=True,
        at_commit=True,
    )
    assert outcome is not None
    assert outcome.error_code == "revision_required"
