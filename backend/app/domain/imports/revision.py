from dataclasses import dataclass
from typing import Literal

from app.domain.imports.dedup import classify_duplicate

CommitAction = Literal["skip", "create", "revise", "link", "reject"]


@dataclass(frozen=True)
class RevisionOutcome:
    action: CommitAction
    error_code: str | None
    advance_watermark_only: bool
    duplicate_status: str
    proposed_action: str
    review_reason: str | None


def evaluate_revision(
    *,
    incoming_revision: int | None,
    incoming_hash: str,
    applied_revision: int | None,
    applied_hash: str | None,
    identity_exists: bool,
    at_commit: bool,
) -> RevisionOutcome | None:
    """None — оставить решение на legacy classify_duplicate (оба revision NULL)."""
    if incoming_revision is None and applied_revision is None:
        return None
    same_hash = applied_hash is not None and applied_hash == incoming_hash
    if applied_revision is not None and incoming_revision is None:
        if same_hash:
            return _outcome("skip", None, False, "repeated", "skip", None)
        return _reject("revision_required", at_commit, "revision_required")

    if incoming_revision is None:
        return None

    if applied_revision is None:
        if identity_exists:
            if same_hash:
                return _outcome("skip", None, True, "repeated", "skip", None)
            return _outcome("revise", None, False, "changed", "revise", None)
        return _outcome("create", None, False, "new", "create", None)

    if incoming_revision < applied_revision:
        return _reject("stale_revision", at_commit, "stale_revision")
    if incoming_revision == applied_revision:
        if same_hash:
            return _outcome("skip", None, False, "repeated", "skip", None)
        return _reject(
            "revision_payload_conflict",
            at_commit,
            "revision_payload_conflict",
        )
    if same_hash:
        return _outcome("skip", None, True, "repeated", "skip", None)
    return _outcome("revise", None, False, "changed", "revise", None)


def merge_preview_decision(
    *,
    has_errors: bool,
    operation: str,
    identity_hash: str | None,
    payload_hash: str,
    other_ids: tuple[str, ...],
    authoritative: bool,
    incoming_revision: int | None,
    applied_revision: int | None,
    identity_exists: bool,
) -> RevisionOutcome:
    if operation == "unpost":
        return _outcome("skip", None, False, "unpost", "review", "unpost")
    if has_errors:
        return _outcome("skip", None, False, "invalid", "skip", None)
    revision = evaluate_revision(
        incoming_revision=incoming_revision,
        incoming_hash=payload_hash,
        applied_revision=applied_revision,
        applied_hash=identity_hash,
        identity_exists=identity_exists,
        at_commit=False,
    )
    if revision is not None:
        return revision
    status, action = classify_duplicate(
        has_errors=False,
        identity_hash=identity_hash,
        payload_hash=payload_hash,
        other_ids=other_ids,
        authoritative=authoritative,
    )
    return _outcome(
        _preview_action(action),
        None,
        False,
        status,
        action,
        None,
    )


def commit_decision(
    *,
    has_errors: bool,
    operation: str,
    identity_hash: str | None,
    payload_hash: str,
    other_ids: tuple[str, ...],
    authoritative: bool,
    incoming_revision: int | None,
    applied_revision: int | None,
    preview_action: str,
    identity_exists: bool,
) -> RevisionOutcome:
    if operation == "unpost":
        return _outcome("skip", None, False, "unpost", "review", "unpost")
    if has_errors:
        return _outcome("reject", "validation_error", False, "invalid", "skip", None)
    revision = evaluate_revision(
        incoming_revision=incoming_revision,
        incoming_hash=payload_hash,
        applied_revision=applied_revision,
        applied_hash=identity_hash,
        identity_exists=identity_exists,
        at_commit=True,
    )
    if revision is not None:
        if revision.error_code is not None:
            return revision
        if revision.action in {"skip", "create", "revise"}:
            return revision
    status, action = classify_duplicate(
        has_errors=False,
        identity_hash=identity_hash,
        payload_hash=payload_hash,
        other_ids=other_ids,
        authoritative=authoritative,
    )
    mapped = _commit_action(action, preview_action)
    return _outcome(mapped, None, False, status, action, None)


def _preview_action(action: str) -> CommitAction:
    if action in {"create", "revise", "link", "skip"}:
        return action  # type: ignore[return-value]
    return "skip"


def _commit_action(classify_action: str, preview_action: str) -> CommitAction:
    if classify_action in {"create", "revise", "link"}:
        return classify_action  # type: ignore[return-value]
    if classify_action == "skip":
        return "skip"
    linked_preview = preview_action in {"create", "revise", "link"}
    if linked_preview and classify_action in {"ambiguous", "linked"}:
        return preview_action  # type: ignore[return-value]
    return "skip"


def _reject(code: str, at_commit: bool, review_reason: str) -> RevisionOutcome:
    duplicate_status = "repeated" if code == "stale_revision" else "changed"
    if at_commit:
        return _outcome("reject", code, False, duplicate_status, "review", review_reason)
    return _outcome("skip", None, False, duplicate_status, "review", review_reason)


def _outcome(
    action: CommitAction,
    error_code: str | None,
    advance_watermark_only: bool,
    duplicate_status: str,
    proposed_action: str,
    review_reason: str | None,
) -> RevisionOutcome:
    return RevisionOutcome(
        action=action,
        error_code=error_code,
        advance_watermark_only=advance_watermark_only,
        duplicate_status=duplicate_status,
        proposed_action=proposed_action,
        review_reason=review_reason,
    )
