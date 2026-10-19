"""FA-R02.4: control totals, commit gates, coverage reconcile."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from uuid import uuid4

import pytest
from tests.integration.test_import_revision_unpost import (
    CASH_HEADER,
    DatasetCase,
    _ready,
    _source,
)
from tests.integration.test_ingestion_http import (
    _envelope,
    _part_meta,
    _post_ingest,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"


@pytest.fixture
def session_ingest(app):
    app.state.settings.session_ingest_enabled = True
    yield
    app.state.settings.session_ingest_enabled = False


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _envelope_v11(
    connection_id: str,
    delivery_key: str,
    content: bytes,
    *,
    record_count: int,
    cash_in: str,
    cash_out: str,
) -> str:
    return json.dumps(
        {
            "schema_version": "1.1-session",
            "delivery_key": delivery_key,
            "connection_id": connection_id,
            "channel": "ui",
            "mode": "delta",
            "period_from": "2026-10-01",
            "period_to": "2026-10-31",
            "control_totals": {
                "record_count": record_count,
                "currency": "RUB",
                "cash_in": cash_in,
                "cash_out": cash_out,
            },
            "parts": [
                {
                    "part_index": 1,
                    "dataset": "cash",
                    "format": "csv",
                    "content_sha256": _digest(content),
                }
            ],
        }
    )


def test_control_totals_matched_and_commit_with_delivery_id(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "totals-ok@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "tot-ok", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    envelope = _envelope_v11(
        source["id"],
        key,
        blob,
        record_count=2,
        cash_in="3000.00",
        cash_out="0.00",
    )
    created = _post_ingest(client, company_id, envelope, [blob], key)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["validation_status"] == "matched"
    delivery_id = body["delivery_id"]
    batch_id = body["parts"][0]["batch_id"]
    commit = client.post(
        f"/api/v1/imports/{batch_id}/commit?delivery_id={delivery_id}",
    )
    assert commit.status_code == 200, commit.text


def test_control_totals_mismatch_blocks_commit(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "totals-bad@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "tot-bad", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    envelope = _envelope_v11(
        source["id"],
        key,
        blob,
        record_count=2,
        cash_in="999.00",
        cash_out="0.00",
    )
    created = _post_ingest(client, company_id, envelope, [blob], key)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["validation_status"] == "mismatch"
    delivery_id = body["delivery_id"]
    batch_id = body["parts"][0]["batch_id"]
    commit = client.post(
        f"/api/v1/imports/{batch_id}/commit?delivery_id={delivery_id}",
    )
    assert commit.status_code == 409
    assert commit.json()["code"] == "control_totals_mismatch"


def test_session_v10_fingerprint_unchanged() -> None:
    from app.services.ingestion_delivery_service import session_request_fingerprint

    company_id = uuid.uuid4()
    conn_id = uuid.uuid4()
    digest = "a" * 64
    manifest = [(1, "cash", "csv", digest)]
    first = session_request_fingerprint(company_id, conn_id, manifest)
    second = session_request_fingerprint(company_id, conn_id, manifest)
    assert first == second
    assert len(first) == 64


def test_reconcile_requires_commit_and_idempotent(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "reconcile@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "rec", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    envelope = _envelope_v11(
        source["id"],
        key,
        blob,
        record_count=2,
        cash_in="3000.00",
        cash_out="0.00",
    )
    created = _post_ingest(client, company_id, envelope, [blob], key)
    assert created.status_code == 201
    delivery_id = created.json()["delivery_id"]
    batch_id = created.json()["parts"][0]["batch_id"]
    before_commit = client.post(
        f"/api/v1/ingestions/{delivery_id}/reconcile",
        json={"reconciliation_basis": "ручная сверка"},
        headers={"Idempotency-Key": "rec-1"},
    )
    assert before_commit.status_code == 409
    client.post(f"/api/v1/imports/{batch_id}/commit?delivery_id={delivery_id}")
    reconciled = client.post(
        f"/api/v1/ingestions/{delivery_id}/reconcile",
        json={"reconciliation_basis": "ручная сверка"},
        headers={"Idempotency-Key": "rec-1"},
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["state"] == "reconciled"
    again = client.post(
        f"/api/v1/ingestions/{delivery_id}/reconcile",
        json={"reconciliation_basis": "ручная сверка"},
        headers={"Idempotency-Key": "rec-1"},
    )
    assert again.status_code == 200
    assert again.json()["id"] == reconciled.json()["id"]


def test_v10_envelope_still_works(client, admin, app, fake, tmp_path, session_ingest) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "v10@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "v10", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    env = _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob)])
    created = _post_ingest(client, company_id, env, [blob], key)
    assert created.status_code == 201
    assert created.json()["validation_status"] == "not_checked"
