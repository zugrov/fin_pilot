import hashlib
import json
import uuid

import pytest
from app.errors import AppError
from app.schemas.session_ingestion import parse_envelope_json
from app.services.ingestion_delivery_service import session_request_fingerprint


def _sample_envelope(extra: dict | None = None) -> str:
    connection_id = str(uuid.uuid4())
    payload = {
        "schema_version": "1.0-session",
        "delivery_key": "key-1",
        "connection_id": connection_id,
        "channel": "ui",
        "parts": [
            {
                "part_index": 1,
                "dataset": "cash",
                "format": "csv",
                "content_sha256": "a" * 64,
            }
        ],
    }
    if extra:
        payload.update(extra)
    return json.dumps(payload)


def test_parse_valid_envelope() -> None:
    parsed = parse_envelope_json(_sample_envelope())
    assert parsed.channel == "ui"
    assert parsed.schema_version == "1.0-session"


def test_reject_extra_envelope_field() -> None:
    raw = json.loads(_sample_envelope())
    raw["client_package_id"] = "pkg"
    with pytest.raises(AppError) as exc:
        parse_envelope_json(json.dumps(raw))
    assert exc.value.status_code == 422


def test_reject_api_channel() -> None:
    raw = json.loads(_sample_envelope())
    raw["channel"] = "api"
    with pytest.raises(AppError):
        parse_envelope_json(json.dumps(raw))


def test_parse_v11_snapshot_requires_control_totals() -> None:
    raw = json.loads(_sample_envelope())
    raw["schema_version"] = "1.1-session"
    raw["mode"] = "snapshot"
    raw["period_from"] = "2026-10-01"
    raw["period_to"] = "2026-10-31"
    with pytest.raises(AppError):
        parse_envelope_json(json.dumps(raw))


def test_session_fingerprint_order_independent() -> None:
    company_id = uuid.uuid4()
    connection_id = uuid.uuid4()
    digest_a = hashlib.sha256(b"a").hexdigest()
    digest_b = hashlib.sha256(b"b").hexdigest()
    first = session_request_fingerprint(
        company_id,
        connection_id,
        [(2, "cash", "csv", digest_b), (1, "cash", "csv", digest_a)],
    )
    second = session_request_fingerprint(
        company_id,
        connection_id,
        [(1, "cash", "csv", digest_a), (2, "cash", "csv", digest_b)],
    )
    assert first == second
