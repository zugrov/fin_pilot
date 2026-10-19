from app.domain.imports.import_meta import parse_row_meta


def test_source_entity_id_alias_must_match() -> None:
    meta = parse_row_meta({"external_id": "a", "source_entity_id": "b", "operation": "upsert"})
    assert "source_entity_id_conflict" in meta.errors


def test_unknown_operation_rejected() -> None:
    meta = parse_row_meta({"external_id": "x", "operation": "delete"})
    assert "unknown_operation" in meta.errors


def test_malformed_revision() -> None:
    meta = parse_row_meta({"external_id": "x", "source_revision": "1.5", "operation": "upsert"})
    assert "bad_source_revision" in meta.errors
