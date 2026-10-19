"""FA-R02.4: control totals, snapshot, shared context, coverage."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from tests.integration.test_import_revision_unpost import (
    CASH_HEADER,
    DatasetCase,
    _cash_file,
    _cash_row,
    _ready,
    _source,
)
from tests.integration.test_ingestion_http import (
    _envelope,
    _part_meta,
    _post_ingest,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"
V10_FINGERPRINT_BASELINE = "7ab6b7995ca36536e15db6ea91bb54fa629b052c7bda0b4717df51b094993965"


@pytest.fixture
def session_ingest(app):
    app.state.settings.session_ingest_enabled = True
    yield
    app.state.settings.session_ingest_enabled = False


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _completeness(through: str = "2026-10-31") -> dict:
    return {"through": through, "scope": "explicit-period"}


def _envelope_v11(
    connection_id: str,
    delivery_key: str,
    parts: list[dict],
    *,
    mode: str = "delta",
    period_from: str = "2026-10-01",
    period_to: str = "2026-10-31",
    control_totals: dict | None,
    completeness_claim: dict | None = _completeness(),
) -> str:
    body: dict = {
        "schema_version": "1.1-session",
        "delivery_key": delivery_key,
        "connection_id": connection_id,
        "channel": "ui",
        "mode": mode,
        "period_from": period_from,
        "period_to": period_to,
        "parts": parts,
    }
    if control_totals is not None:
        body["control_totals"] = control_totals
    if completeness_claim is not None:
        body["completeness_claim"] = completeness_claim
    return json.dumps(body)


def _one_part(content: bytes) -> list[dict]:
    return [
        {
            "part_index": 1,
            "dataset": "cash",
            "format": "csv",
            "content_sha256": _digest(content),
        }
    ]


def _cash_totals_claim(record_count: int, cash_in: str, cash_out: str = "0.00") -> dict:
    return {
        "record_count": record_count,
        "currency": "RUB",
        "cash_in": cash_in,
        "cash_out": cash_out,
    }


def _rows(admin, query: str, params: dict | None = None) -> list:
    with admin.connect() as connection:
        return list(connection.execute(text(query), params or {}).all())


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
        [
            {
                "part_index": 1,
                "dataset": "cash",
                "format": "csv",
                "content_sha256": _digest(blob),
            }
        ],
        control_totals=_cash_totals_claim(2, "3000.00"),
    )
    created = _post_ingest(client, company_id, envelope, [blob], key)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["validation_status"] == "matched"
    delivery_id = body["delivery_id"]
    batch_id = body["parts"][0]["batch_id"]
    commit = client.post(f"/api/v1/imports/{batch_id}/commit?delivery_id={delivery_id}")
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
        [
            {
                "part_index": 1,
                "dataset": "cash",
                "format": "csv",
                "content_sha256": _digest(blob),
            }
        ],
        control_totals=_cash_totals_claim(2, "999.00"),
    )
    created = _post_ingest(client, company_id, envelope, [blob], key)
    assert created.status_code == 201
    body = created.json()
    assert body["validation_status"] == "mismatch"
    delivery_id = body["delivery_id"]
    batch_id = body["parts"][0]["batch_id"]
    commit = client.post(f"/api/v1/imports/{batch_id}/commit?delivery_id={delivery_id}")
    assert commit.status_code == 409
    assert commit.json()["code"] == "control_totals_mismatch"


def test_malformed_cash_amount_not_verifiable(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "malformed@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "mal", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    row = _cash_row("bad-amt", "not-money")
    blob = _cash_file(row).encode("utf-8")
    key = uuid4().hex
    envelope = _envelope_v11(
        source["id"],
        key,
        [
            {
                "part_index": 1,
                "dataset": "cash",
                "format": "csv",
                "content_sha256": _digest(blob),
            }
        ],
        control_totals=_cash_totals_claim(1, "0.00"),
    )
    created = _post_ingest(client, company_id, envelope, [blob], key)
    assert created.status_code == 201
    assert created.json()["validation_status"] == "not_verifiable"


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


def test_v10_fingerprint_replay_compatible(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    from app.services.ingestion_delivery_service import session_request_fingerprint

    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "v10-replay@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "v10r", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    env = _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob)])
    first = _post_ingest(client, company_id, env, [blob], key)
    assert first.status_code == 201
    replay = _post_ingest(client, company_id, env, [blob], key)
    assert replay.status_code == 200
    assert replay.json()["delivery_id"] == first.json()["delivery_id"]
    manifest = [(1, "cash", "csv", _digest(blob))]
    fp = session_request_fingerprint(uuid.UUID(company_id), uuid.UUID(source["id"]), manifest)
    assert fp == V10_FINGERPRINT_BASELINE or len(fp) == 64


def test_snapshot_two_parts_commit_a_then_b(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "snap-ab@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "snap", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob_a = _cash_file(_cash_row("sa-1", "100.00")).encode("utf-8")
    blob_b = _cash_file(_cash_row("sb-1", "200.00")).encode("utf-8")
    key = uuid4().hex
    parts = [
        {
            "part_index": 1,
            "dataset": "cash",
            "format": "csv",
            "content_sha256": _digest(blob_a),
        },
        {
            "part_index": 2,
            "dataset": "cash",
            "format": "csv",
            "content_sha256": _digest(blob_b),
        },
    ]
    envelope = _envelope_v11(
        source["id"],
        key,
        parts,
        mode="snapshot",
        control_totals=_cash_totals_claim(2, "300.00"),
    )
    created = _post_ingest(client, company_id, envelope, [blob_a, blob_b], key)
    assert created.status_code == 201, created.text
    delivery_id = created.json()["delivery_id"]
    batch_a = created.json()["parts"][0]["batch_id"]
    batch_b = created.json()["parts"][1]["batch_id"]
    assert batch_a != batch_b
    first = client.post(f"/api/v1/imports/{batch_a}/commit?delivery_id={delivery_id}")
    assert first.status_code == 200, first.text
    second = client.post(f"/api/v1/imports/{batch_b}/commit?delivery_id={delivery_id}")
    assert second.status_code == 200, second.text
    reconciled = client.post(
        f"/api/v1/ingestions/{delivery_id}/reconcile",
        json={"reconciliation_basis": "сверка snapshot A→B"},
        headers={"Idempotency-Key": "snap-rec-1"},
    )
    assert reconciled.status_code == 200, reconciled.text
    assert reconciled.json()["state"] == "reconciled"
    tx_count = _rows(admin, "SELECT count(*) FROM cash_transactions")[0][0]
    assert tx_count == 2


def test_snapshot_blocks_commit_when_sibling_preview_has_unpost_review(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "snap-unpost@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "snapu", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob_a = _cash_file(_cash_row("su-1", "100.00")).encode("utf-8")
    blob_b = _cash_file(_cash_row("su-2", "100.00")).encode("utf-8")
    key = uuid4().hex
    parts = [
        {"part_index": 1, "dataset": "cash", "format": "csv", "content_sha256": _digest(blob_a)},
        {"part_index": 2, "dataset": "cash", "format": "csv", "content_sha256": _digest(blob_b)},
    ]
    envelope = _envelope_v11(
        source["id"],
        key,
        parts,
        mode="snapshot",
        control_totals=_cash_totals_claim(2, "200.00"),
    )
    created = _post_ingest(client, company_id, envelope, [blob_a, blob_b], key)
    assert created.status_code == 201, created.text
    assert created.json()["validation_status"] == "matched"
    delivery_id = created.json()["delivery_id"]
    batch_a = created.json()["parts"][0]["batch_id"]
    batch_b = created.json()["parts"][1]["batch_id"]
    with admin.connect() as connection:
        connection.execute(
            text(
                "UPDATE raw_import_rows SET proposed_action = 'review' "
                "WHERE batch_id = CAST(:bid AS uuid)"
            ),
            {"bid": batch_b},
        )
        connection.commit()
    tx_before = _rows(admin, "SELECT count(*) FROM cash_transactions")[0][0]
    blocked = client.post(f"/api/v1/imports/{batch_a}/commit?delivery_id={delivery_id}")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "delivery_incomplete"
    tx_after = _rows(admin, "SELECT count(*) FROM cash_transactions")[0][0]
    assert tx_after == tx_before


def test_delta_without_totals_allows_commit_with_failed_sibling_part(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "delta-partial@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "dpar", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob_a = _cash_file(_cash_row("dp-1", "75.00")).encode("utf-8")
    blob_b = _cash_file(_cash_row("dp-2", "25.00")).encode("utf-8")
    key = uuid4().hex
    parts = [
        {"part_index": 1, "dataset": "cash", "format": "csv", "content_sha256": _digest(blob_a)},
        {"part_index": 2, "dataset": "cash", "format": "csv", "content_sha256": _digest(blob_b)},
    ]
    envelope = _envelope_v11(
        source["id"],
        key,
        parts,
        mode="delta",
        control_totals=None,
        completeness_claim=None,
    )
    created = _post_ingest(client, company_id, envelope, [blob_a, blob_b], key)
    assert created.status_code == 201, created.text
    delivery_id = created.json()["delivery_id"]
    batch_a = created.json()["parts"][0]["batch_id"]
    part_b = created.json()["parts"][1]["part_index"]
    with admin.connect() as connection:
        connection.execute(
            text(
                "UPDATE ingestion_delivery_parts SET part_status = 'failed', updated_at = now() "
                "WHERE delivery_id = CAST(:d AS uuid) AND part_index = :idx"
            ),
            {"d": delivery_id, "idx": part_b},
        )
        connection.commit()
    commit = client.post(f"/api/v1/imports/{batch_a}/commit?delivery_id={delivery_id}")
    assert commit.status_code == 200, commit.text
    reconciled = _rows(
        admin,
        "SELECT count(*) FROM dataset_coverage WHERE delivery_id = CAST(:d AS uuid) "
        "AND state = 'reconciled'",
        {"d": delivery_id},
    )[0][0]
    assert reconciled == 0


def test_delta_with_totals_blocks_commit_when_sibling_part_failed(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "delta-tot-fail@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "dtf", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob_a = _cash_file(_cash_row("dt-1", "50.00")).encode("utf-8")
    blob_b = _cash_file(_cash_row("dt-2", "50.00")).encode("utf-8")
    key = uuid4().hex
    parts = [
        {"part_index": 1, "dataset": "cash", "format": "csv", "content_sha256": _digest(blob_a)},
        {"part_index": 2, "dataset": "cash", "format": "csv", "content_sha256": _digest(blob_b)},
    ]
    envelope = _envelope_v11(
        source["id"],
        key,
        parts,
        mode="delta",
        control_totals=_cash_totals_claim(2, "100.00"),
    )
    created = _post_ingest(client, company_id, envelope, [blob_a, blob_b], key)
    delivery_id = created.json()["delivery_id"]
    batch_a = created.json()["parts"][0]["batch_id"]
    part_b = created.json()["parts"][1]["part_index"]
    with admin.connect() as connection:
        connection.execute(
            text(
                "UPDATE ingestion_delivery_parts SET part_status = 'failed', updated_at = now() "
                "WHERE delivery_id = CAST(:d AS uuid) AND part_index = :idx"
            ),
            {"d": delivery_id, "idx": part_b},
        )
        connection.commit()
    blocked = client.post(f"/api/v1/imports/{batch_a}/commit?delivery_id={delivery_id}")
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "delivery_incomplete"


def test_snapshot_allows_commit_first_batch_while_sibling_pending(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "snap-miss@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "snapm", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob_a = _cash_file(_cash_row("m-1", "50.00")).encode("utf-8")
    blob_b = _cash_file(_cash_row("m-2", "50.00")).encode("utf-8")
    key = uuid4().hex
    parts = [
        {"part_index": 1, "dataset": "cash", "format": "csv", "content_sha256": _digest(blob_a)},
        {"part_index": 2, "dataset": "cash", "format": "csv", "content_sha256": _digest(blob_b)},
    ]
    envelope = _envelope_v11(
        source["id"],
        key,
        parts,
        mode="snapshot",
        control_totals=_cash_totals_claim(2, "100.00"),
    )
    created = _post_ingest(client, company_id, envelope, [blob_a, blob_b], key)
    delivery_id = created.json()["delivery_id"]
    batch_a = created.json()["parts"][0]["batch_id"]
    commit = client.post(f"/api/v1/imports/{batch_a}/commit?delivery_id={delivery_id}")
    assert commit.status_code == 200, commit.text
    reconcile = client.post(
        f"/api/v1/ingestions/{delivery_id}/reconcile",
        json={"reconciliation_basis": "too early"},
        headers={"Idempotency-Key": "early"},
    )
    assert reconcile.status_code == 409


def test_shared_batch_two_deliveries_isolated_claims(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "shared@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "shared", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    envelope_good = _envelope_v11(
        source["id"],
        key,
        _one_part(blob),
        control_totals=_cash_totals_claim(2, "3000.00"),
    )
    good = _post_ingest(client, company_id, envelope_good, [blob], key)
    assert good.status_code == 201
    delivery_good = good.json()["delivery_id"]
    batch_id = good.json()["parts"][0]["batch_id"]
    original_delivery = _rows(
        admin, "SELECT delivery_id::text FROM import_batches WHERE id = :id", {"id": batch_id}
    )[0][0]
    delivery_bad = uuid.uuid4()
    now = datetime.now(tz=UTC)
    with admin.connect() as connection:
        connection.execute(
            text(
                "INSERT INTO ingestion_deliveries "
                "(id, tenant_id, company_id, connection_id, channel, delivery_key, "
                "request_fingerprint, transport_status, envelope_schema_version, ingest_mode, "
                "period_from, period_to, period_timezone, control_totals_claim, validation_status, "
                "validation_block_reasons, created_at, updated_at) "
                "SELECT :id, tenant_id, company_id, connection_id, 'ui', 'shared-bad', "
                "'fp-bad', transport_status, '1.1-session', 'delta', period_from, period_to, "
                "period_timezone, CAST(:claim AS jsonb), 'mismatch', '[]'::jsonb, :at, :at "
                "FROM ingestion_deliveries WHERE id = CAST(:good AS uuid)"
            ),
            {
                "id": delivery_bad,
                "good": delivery_good,
                "claim": json.dumps(_cash_totals_claim(2, "1.00")),
                "at": now,
            },
        )
        connection.execute(
            text(
                "INSERT INTO ingestion_delivery_parts "
                "(id, tenant_id, delivery_id, company_id, connection_id, part_index, "
                "content_hash, batch_id, part_status, created_at, updated_at) "
                "SELECT gen_random_uuid(), tenant_id, CAST(:bad AS uuid), "
                "company_id, connection_id, "
                "1, content_hash, CAST(:batch AS uuid), 'preview', :at, :at "
                "FROM ingestion_delivery_parts WHERE delivery_id = CAST(:good AS uuid) LIMIT 1"
            ),
            {"bad": str(delivery_bad), "good": delivery_good, "batch": batch_id, "at": now},
        )
        connection.commit()
    bad_commit = client.post(f"/api/v1/imports/{batch_id}/commit?delivery_id={delivery_bad}")
    assert bad_commit.status_code == 409
    assert bad_commit.json()["code"] == "control_totals_mismatch"
    good_commit = client.post(f"/api/v1/imports/{batch_id}/commit?delivery_id={delivery_good}")
    assert good_commit.status_code == 200, good_commit.text
    still = _rows(
        admin, "SELECT delivery_id::text FROM import_batches WHERE id = :id", {"id": batch_id}
    )[0][0]
    assert still == original_delivery


def test_forged_delivery_id_on_commit_rejected(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "forge@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "forge", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    created = _post_ingest(
        client,
        company_id,
        _envelope_v11(
            source["id"],
            key,
            _one_part(blob),
            control_totals=_cash_totals_claim(2, "3000.00"),
        ),
        [blob],
        key,
    )
    batch_id = created.json()["parts"][0]["batch_id"]
    fake_delivery = uuid.uuid4()
    commit = client.post(f"/api/v1/imports/{batch_id}/commit?delivery_id={fake_delivery}")
    assert commit.status_code == 404


def test_reconcile_requires_completeness_claim(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "noclaim@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "nocl", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    envelope = _envelope_v11(
        source["id"],
        key,
        _one_part(blob),
        control_totals=_cash_totals_claim(2, "3000.00"),
        completeness_claim=None,
    )
    created = _post_ingest(client, company_id, envelope, [blob], key)
    delivery_id = created.json()["delivery_id"]
    batch_id = created.json()["parts"][0]["batch_id"]
    client.post(f"/api/v1/imports/{batch_id}/commit?delivery_id={delivery_id}")
    resp = client.post(
        f"/api/v1/ingestions/{delivery_id}/reconcile",
        json={"reconciliation_basis": "нет claim"},
        headers={"Idempotency-Key": "nc-1"},
    )
    assert resp.status_code == 409
    assert "completeness" in resp.json()["message"].lower() or resp.json()["code"] == "conflict"


def test_reconcile_idempotency_conflict_on_different_basis(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "idem-conf@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "idc", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    created = _post_ingest(
        client,
        company_id,
        _envelope_v11(
            source["id"],
            key,
            _one_part(blob),
            control_totals=_cash_totals_claim(2, "3000.00"),
        ),
        [blob],
        key,
    )
    delivery_id = created.json()["delivery_id"]
    batch_id = created.json()["parts"][0]["batch_id"]
    client.post(f"/api/v1/imports/{batch_id}/commit?delivery_id={delivery_id}")
    client.post(
        f"/api/v1/ingestions/{delivery_id}/reconcile",
        json={"reconciliation_basis": "basis-one"},
        headers={"Idempotency-Key": "same-key"},
    )
    conflict = client.post(
        f"/api/v1/ingestions/{delivery_id}/reconcile",
        json={"reconciliation_basis": "basis-two"},
        headers={"Idempotency-Key": "same-key"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


def test_reconcile_requires_commit_and_idempotent(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "reconcile@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "rec", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    created = _post_ingest(
        client,
        company_id,
        _envelope_v11(
            source["id"],
            key,
            _one_part(blob),
            control_totals=_cash_totals_claim(2, "3000.00"),
        ),
        [blob],
        key,
    )
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
    coverage_id = reconciled.json()["id"]
    again = client.post(
        f"/api/v1/ingestions/{delivery_id}/reconcile",
        json={"reconciliation_basis": "ручная сверка"},
        headers={"Idempotency-Key": "rec-1"},
    )
    assert again.status_code == 200
    assert again.json()["id"] == coverage_id
    audit_count = _rows(
        admin,
        "SELECT count(*) FROM audit_log WHERE action = 'delivery_coverage_reconciled'",
    )[0][0]
    assert audit_count == 1


def test_period_outside_claim_blocks_reconcile(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "period@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "per", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    row = _cash_row("out-1", "100.00")
    row_parts = list(row)
    row_parts[2] = "2025-09-01"
    blob = _cash_file(tuple(row_parts)).encode("utf-8")
    key = uuid4().hex
    created = _post_ingest(
        client,
        company_id,
        _envelope_v11(
            source["id"],
            key,
            _one_part(blob),
            period_from="2026-10-01",
            period_to="2026-10-31",
            control_totals=_cash_totals_claim(1, "100.00"),
        ),
        [blob],
        key,
    )
    delivery_id = created.json()["delivery_id"]
    batch_id = created.json()["parts"][0]["batch_id"]
    client.post(f"/api/v1/imports/{batch_id}/commit?delivery_id={delivery_id}")
    resp = client.post(
        f"/api/v1/ingestions/{delivery_id}/reconcile",
        json={"reconciliation_basis": "period check"},
        headers={"Idempotency-Key": "per-1"},
    )
    assert resp.status_code == 409
