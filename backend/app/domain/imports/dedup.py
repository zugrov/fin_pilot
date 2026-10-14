def classify_duplicate(
    *,
    has_errors: bool,
    identity_hash: str | None,
    payload_hash: str,
    other_ids: tuple[str, ...],
    authoritative: bool,
) -> tuple[str, str]:
    if has_errors:
        return "invalid", "skip"
    if identity_hash is not None:
        if identity_hash == payload_hash:
            return "repeated", "skip"
        return "changed", "revise"
    distinct = tuple(dict.fromkeys(other_ids))
    if len(distinct) > 1:
        return "ambiguous", "review"
    if len(distinct) == 1:
        return "linked", "link"
    if authoritative:
        return "new", "create"
    return "ambiguous", "review"
