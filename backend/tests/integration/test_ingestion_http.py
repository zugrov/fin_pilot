import hashlib
import json
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from tests.integration.conftest import login, register_and_verify
from tests.integration.test_import_revision_unpost import (
    CASH_HEADER,
    DatasetCase,
    _cash_file,
    _cash_row,
    _ready,
    _source,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _envelope(connection_id: str, delivery_key: str, parts: list[dict]) -> str:
    return json.dumps(
        {
            "schema_version": "1.0-session",
            "delivery_key": delivery_key,
            "connection_id": connection_id,
            "channel": "ui",
            "parts": parts,
        }
    )


def _part_meta(index: int, dataset: str, fmt: str, content: bytes) -> dict:
    return {
        "part_index": index,
        "dataset": dataset,
        "format": fmt,
        "content_sha256": _digest(content),
    }


def _post_ingest(client, company_id: str, envelope: str, blobs: list[bytes], key: str):
    files = [
        ("files", (f"part{i + 1}.csv", blob, "application/octet-stream"))
        for i, blob in enumerate(blobs)
    ]
    return client.post(
        f"/api/v1/companies/{company_id}/ingestions",
        data={"envelope": envelope},
        files=files,
        headers={"Idempotency-Key": key},
    )


@pytest.fixture
def session_ingest(app):
    app.state.settings.session_ingest_enabled = True
    yield
    app.state.settings.session_ingest_enabled = False


def test_routes_hidden_when_flag_off(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "ing-off@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-off", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    env = _envelope(source["id"], "k1", [_part_meta(1, "cash", "csv", blob)])
    response = _post_ingest(client, company_id, env, [blob], "k1")
    assert response.status_code == 404


def test_success_preview_and_get(client, admin, app, fake, tmp_path, session_ingest) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "ing-ok@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-http", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    env = _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob)])
    created = _post_ingest(client, company_id, env, [blob], key)
    assert created.status_code == 201, created.text
    delivery_id = created.json()["delivery_id"]
    assert created.json()["transport_status"] == "transport_complete"
    part = created.json()["parts"][0]
    assert part["state"] == "preview"
    assert part["batch_id"]
    assert part["links"]["preview"].endswith("/preview")

    fetched = client.get(f"/api/v1/ingestions/{delivery_id}")
    assert fetched.status_code == 200
    assert fetched.json()["transport_status"] == "transport_complete"
    preview = client.get(part["links"]["preview"])
    assert preview.status_code == 200


def test_bearer_rejected(client, admin, app, fake, tmp_path, session_ingest) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "ing-bearer@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-b", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    env = _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob)])
    response = client.post(
        f"/api/v1/companies/{company_id}/ingestions",
        data={"envelope": env},
        files=[("files", ("a.csv", blob, "application/octet-stream"))],
        headers={"Idempotency-Key": key, "Authorization": "Bearer fake"},
    )
    assert response.status_code == 401


def test_idempotency_replay_and_conflict(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "ing-idem@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-id", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    env = _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob)])
    first = _post_ingest(client, company_id, env, [blob], key)
    assert first.status_code == 201
    second = _post_ingest(client, company_id, env, [blob], key)
    assert second.status_code == 200
    assert second.json() == first.json()

    other_blob = blob + b"\n"
    bad_meta = _part_meta(1, "cash", "csv", other_blob)
    bad_env = _envelope(source["id"], key, [bad_meta])
    conflict = _post_ingest(client, company_id, bad_env, [other_blob], key)
    assert conflict.status_code == 409


def test_partial_and_all_failed(client, admin, app, fake, tmp_path, session_ingest) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "ing-part@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-partial", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    good = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    bad = b"not-a-valid-csv-or-format"
    key = uuid4().hex
    env = _envelope(
        source["id"],
        key,
        [_part_meta(1, "cash", "csv", good), _part_meta(2, "cash", "csv", bad)],
    )
    response = _post_ingest(client, company_id, env, [good, bad], key)
    assert response.status_code == 201
    body = response.json()
    assert body["transport_status"] == "partially_received"
    states = {item["part_index"]: item["state"] for item in body["parts"]}
    assert states[1] == "preview"
    assert states[2] == "failed"

    key2 = uuid4().hex
    only_bad_blob = b"%%%invalid"
    env2 = _envelope(source["id"], key2, [_part_meta(1, "cash", "csv", only_bad_blob)])
    only_bad = _post_ingest(client, company_id, env2, [only_bad_blob], key2)
    assert only_bad.status_code == 201
    assert only_bad.json()["transport_status"] == "transport_rejected"


def test_revision_via_ingest(client, admin, app, fake, tmp_path, session_ingest) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "ing-rev@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-rev", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    row = _cash_file(_cash_row("rev-1", "100.00", revision=1)).encode()
    key = uuid4().hex
    env = _envelope(source["id"], key, [_part_meta(1, "cash", "csv", row)])
    first = _post_ingest(client, company_id, env, [row], key)
    assert first.status_code == 201
    batch_id = first.json()["parts"][0]["batch_id"]
    commit = client.post(f"/api/v1/imports/{batch_id}/commit")
    assert commit.status_code == 200

    row2 = _cash_file(_cash_row("rev-1", "200.00", revision=2)).encode()
    key2 = uuid4().hex
    env2 = _envelope(source["id"], key2, [_part_meta(1, "cash", "csv", row2)])
    second = _post_ingest(client, company_id, env2, [row2], key2)
    assert second.status_code == 201
    preview = client.get(f"/api/v1/imports/{second.json()['parts'][0]['batch_id']}/preview")
    assert preview.status_code == 200
    statuses = {item["duplicate_status"] for item in preview.json()["rows"]}
    assert "changed" in statuses


def test_same_bytes_shared_batch(client, admin, app, fake, tmp_path, session_ingest) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "ing-share@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-share", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key1 = uuid4().hex
    env1 = _envelope(source["id"], key1, [_part_meta(1, "cash", "csv", blob)])
    first = _post_ingest(client, company_id, env1, [blob], key1)
    key2 = uuid4().hex
    env2 = _envelope(source["id"], key2, [_part_meta(1, "cash", "csv", blob)])
    second = _post_ingest(client, company_id, env2, [blob], key2)
    assert first.json()["parts"][0]["batch_id"] == second.json()["parts"][0]["batch_id"]
    assert first.json()["delivery_id"] != second.json()["delivery_id"]


def test_unsupported_envelope_field(client, admin, app, fake, tmp_path, session_ingest) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "ing-extra@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-x", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    raw = json.loads(_envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob)]))
    raw["mode"] = "snapshot"
    response = _post_ingest(client, company_id, json.dumps(raw), [blob], key)
    assert response.status_code == 422


def test_concurrent_same_key(client, admin, app, fake, tmp_path, session_ingest) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "ing-conc@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-conc", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    env = _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob)])
    barrier = threading.Barrier(2)
    results: list[int] = []

    def worker() -> None:
        barrier.wait()
        response = _post_ingest(client, company_id, env, [blob], key)
        results.append(response.status_code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(results) == [200, 201] or results == [201, 201]


def test_get_foreign_delivery_not_found(client, admin, app, fake, tmp_path, session_ingest) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "ing-a@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-a", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    env = _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob)])
    created = _post_ingest(client, company_id, env, [blob], key)
    delivery_id = created.json()["delivery_id"]

    register_and_verify(client, admin, "ing-b@example.com")
    login(client, "ing-b@example.com")
    other = client.get(f"/api/v1/ingestions/{delivery_id}")
    assert other.status_code == 404
