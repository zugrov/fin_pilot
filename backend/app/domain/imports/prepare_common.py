from app.domain.imports.import_meta import RowMeta
from app.domain.imports.revision import merge_preview_decision
from app.domain.imports.source_identity_slot import entity_type_conflict
from app.models.imports import SourceIdentity


def classify_import_row(
    *,
    errors: list[str],
    meta: RowMeta,
    identity: SourceIdentity | None,
    entity_type: str,
    payload_hash: str,
    other_ids: tuple[str, ...],
    authoritative: bool,
) -> dict[str, object | tuple[str, ...] | str | int | None]:
    conflict = entity_type_conflict(identity, entity_type)
    if conflict:
        errors.append(conflict)
    has_errors = bool(errors)
    digest = "" if has_errors else payload_hash
    decision = merge_preview_decision(
        has_errors=has_errors,
        operation=meta.operation,
        identity_hash=None if identity is None else identity.payload_hash,
        payload_hash=digest or payload_hash,
        other_ids=other_ids if not has_errors else (),
        authoritative=authoritative,
        incoming_revision=meta.source_revision,
        applied_revision=None if identity is None else identity.last_source_revision,
        identity_exists=identity is not None,
    )
    return {
        "errors": tuple(dict.fromkeys(errors)),
        "duplicate_status": decision.duplicate_status,
        "proposed_action": decision.proposed_action,
        "payload_hash": None if has_errors or not payload_hash else payload_hash,
        "operation": meta.operation,
        "source_revision": meta.source_revision,
        "external_id": meta.external_id or None,
        "review_reason": decision.review_reason or meta.review_reason,
    }
