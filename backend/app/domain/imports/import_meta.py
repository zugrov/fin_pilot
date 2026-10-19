from dataclasses import dataclass

from app.domain.imports.contracts import ImportFormatError

IMPORT_META_COLUMNS = ("source_entity_id", "source_revision", "operation")
MAX_SOURCE_REVISION = 2**63 - 1


def validate_import_header(header: tuple[str, ...], required: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = tuple(item.strip() for item in header)
    if cleaned == required:
        return required
    if len(cleaned) <= len(required) or cleaned[: len(required)] != required:
        raise ImportFormatError("unsupported_format", "Неизвестные колонки CSV")
    extra = cleaned[len(required) :]
    if len(extra) > len(IMPORT_META_COLUMNS):
        raise ImportFormatError("unsupported_format", "Неизвестные колонки CSV")
    for pos, name in enumerate(extra):
        if name != IMPORT_META_COLUMNS[pos]:
            raise ImportFormatError("unsupported_format", "Неизвестные колонки CSV")
    return cleaned


def normalize_external_id_text(value: str) -> str:
    return value.strip()


@dataclass(frozen=True)
class RowMeta:
    external_id: str
    source_revision: int | None
    operation: str
    errors: tuple[str, ...]
    review_reason: str | None


def parse_row_meta(raw: dict[str, str], *, external_id: str | None = None) -> RowMeta:
    errors: list[str] = []
    operation = _parse_operation(raw.get("operation", ""), errors)
    revision = _parse_source_revision(raw.get("source_revision", ""), errors)
    resolved_id, id_errors = _resolve_external_id(raw, external_id)
    errors.extend(id_errors)
    if operation in {"unpost", "upsert"} and revision is not None and not resolved_id:
        errors.append("missing_external_id")
    review_reason = None
    if operation == "unpost":
        review_reason = "unpost"
    deduped = tuple(dict.fromkeys(errors))
    return RowMeta(resolved_id, revision, operation, deduped, review_reason)


def _resolve_external_id(raw: dict[str, str], fallback: str | None) -> tuple[str, list[str]]:
    errors: list[str] = []
    primary = normalize_external_id_text(raw.get("external_id", ""))
    alias = normalize_external_id_text(raw.get("source_entity_id", ""))
    if primary and alias and primary != alias:
        errors.append("source_entity_id_conflict")
        return "", errors
    if alias:
        return alias, errors
    if primary:
        return primary, errors
    if fallback is not None and fallback.strip():
        return normalize_external_id_text(fallback), errors
    errors.append("missing_external_id")
    return "", errors


def _parse_operation(raw: str, errors: list[str]) -> str:
    text = raw.strip().lower()
    if not text:
        return "upsert"
    if text == "upsert":
        return "upsert"
    if text == "unpost":
        return "unpost"
    errors.append("unknown_operation")
    return "upsert"


def _parse_source_revision(raw: str, errors: list[str]) -> int | None:
    text = raw.strip()
    if not text:
        return None
    if text[0] in "+-":
        errors.append("bad_source_revision")
        return None
    if any(ch in text for ch in ".eE,"):
        errors.append("bad_source_revision")
        return None
    if not text.isdigit():
        errors.append("bad_source_revision")
        return None
    value = int(text)
    if value < 0 or value > MAX_SOURCE_REVISION:
        errors.append("bad_source_revision")
        return None
    return value
