import asyncio
import hashlib
import json
import os
import threading
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
import psycopg
import pytest
from app.services import session_ingest_multipart as multipart_mod
from fastapi.testclient import TestClient
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
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


def _multipart_raw(
    boundary: str, parts: list[tuple[str, str | None, bytes]]
) -> bytes:
    chunks: list[bytes] = []
    for name, filename, content in parts:
        chunks.append(f"--{boundary}\r\n".encode())
        if filename is None:
            chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        else:
            chunks.append(
                (
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                    "Content-Type: application/octet-stream\r\n\r\n"
                ).encode()
            )
        chunks.append(content)
        if not content.endswith(b"\r\n"):
            chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks)


def _post_multipart_raw(
    client,
    company_id: str,
    body: bytes,
    boundary: str,
    key: str,
):
    return client.post(
        f"/api/v1/companies/{company_id}/ingestions",
        content=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Idempotency-Key": key,
        },
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


def _run_concurrent_same_key(
    client, admin, app, fake, tmp_path, *, email: str
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, email)
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-conc", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    env = _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob)])
    barrier = threading.Barrier(2)
    results: list[tuple[int, dict]] = []
    errors: list[BaseException] = []
    headers = {
        "X-Tenant-Id": client.headers["X-Tenant-Id"],
        "X-CSRF-Token": client.headers["X-CSRF-Token"],
        "Idempotency-Key": key,
    }
    cookies = dict(client.cookies)

    def worker() -> None:
        barrier.wait(timeout=10)
        local = TestClient(app, raise_server_exceptions=False)
        local.cookies.update(cookies)
        local.headers.update(headers)
        try:
            response = _post_ingest(local, company_id, env, [blob], key)
            results.append((response.status_code, response.json()))
        except BaseException as exc:
            errors.append(exc)
        finally:
            local.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
        assert not thread.is_alive()
    assert errors == [], errors
    assert len(results) == 2
    codes = sorted(code for code, _ in results)
    assert codes == [200, 201]
    bodies = [body for _, body in results]
    assert bodies[0] == bodies[1]
    delivery_id = bodies[0]["delivery_id"]
    assert delivery_id
    assert bodies[0]["transport_status"] == "transport_complete"

    assert _rows(admin, "SELECT count(*) FROM ingestion_deliveries")[0][0] == 1
    assert _rows(admin, "SELECT count(*) FROM ingestion_delivery_parts")[0][0] == 1
    assert _rows(admin, "SELECT count(*) FROM import_batches")[0][0] == 1
    assert (
        _rows(
            admin,
            "SELECT count(*) FROM idempotency_records WHERE scope = 'session-ingest'",
        )[0][0]
        == 1
    )
    assert _rows(admin, "SELECT count(*) FROM raw_import_rows")[0][0] == 2
    assert (
        _rows(
            admin,
            "SELECT count(*) FROM audit_log WHERE action = 'import_received'",
        )[0][0]
        == 1
    )


def _rows(admin, query: str, params: dict | None = None) -> list:
    with admin.connect() as connection:
        return list(connection.execute(text(query), params or {}).all())


def test_concurrent_same_key(client, admin, app, fake, tmp_path, session_ingest) -> None:
    _run_concurrent_same_key(
        client, admin, app, fake, tmp_path, email="ing-conc@example.com"
    )


@pytest.mark.parametrize("attempt", range(20))
def test_concurrent_same_key_stability(
    client, admin, app, fake, tmp_path, session_ingest, attempt: int
) -> None:
    _run_concurrent_same_key(
        client,
        admin,
        app,
        fake,
        tmp_path,
        email=f"ing-conc-stress-{attempt}@example.com",
    )


def test_idempotency_conflict_different_manifest(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "ing-conf@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-conf", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob_a = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    blob_b = blob_a + b"\n"
    key = uuid4().hex
    first = _post_ingest(
        client,
        company_id,
        _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob_a)]),
        [blob_a],
        key,
    )
    assert first.status_code == 201
    second = _post_ingest(
        client,
        company_id,
        _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob_b)]),
        [blob_b],
        key,
    )
    assert second.status_code == 409
    assert second.json()["code"] == "idempotency_conflict"


def test_body_limit_total(client, admin, app, fake, tmp_path, session_ingest) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "ing-limit@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-limit", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    app.state.settings.session_ingest_max_body_bytes = 512
    blob = b"x" * 400
    key = uuid4().hex
    env = _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob)])
    response = _post_ingest(client, company_id, env, [blob], key)
    assert response.status_code == 413
    assert _rows(admin, "SELECT count(*) FROM ingestion_deliveries")[0][0] == 0


def test_ingest_commit_failure_returns_5xx(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "ing-cfail@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-cfail", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    env = _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob)])
    original_commit = Session.commit
    calls = {"n": 0}

    def fail_once(self: Session):
        calls["n"] += 1
        if calls["n"] == 1:
            raise SQLAlchemyError("simulated commit failure")
        return original_commit(self)

    from unittest.mock import patch

    with patch.object(Session, "commit", fail_once):
        local = TestClient(app, raise_server_exceptions=False)
        local.cookies.update(dict(client.cookies))
        local.headers.update(client.headers)
        response = _post_ingest(local, company_id, env, [blob], key)
        local.close()
    assert response.status_code >= 500
    assert _rows(admin, "SELECT count(*) FROM ingestion_deliveries")[0][0] == 0
    assert (
        _rows(
            admin,
            "SELECT count(*) FROM idempotency_records WHERE scope = 'session-ingest'",
        )[0][0]
        == 0
    )


def test_duplicate_envelope_rejected(client, admin, app, fake, tmp_path, session_ingest) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "ing-dup-env@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-dup-env", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    env = _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob)])
    boundary = "----finpilot-ing-dup-env"
    body = _multipart_raw(
        boundary,
        [
            ("envelope", None, env.encode()),
            ("envelope", None, env.encode()),
            ("files", "p.csv", blob),
        ],
    )
    close_calls: list[int] = []
    original_close = multipart_mod.close_upload_files

    async def track_close(uploads):
        close_calls.append(len(list(uploads)))
        await original_close(uploads)

    with patch.object(multipart_mod, "close_upload_files", side_effect=track_close):
        response = _post_multipart_raw(client, company_id, body, boundary, key)
    assert response.status_code == 422
    assert close_calls == [1]
    assert _rows(admin, "SELECT count(*) FROM ingestion_deliveries")[0][0] == 0


def test_unknown_field_closes_uploads(client, admin, app, fake, tmp_path, session_ingest) -> None:
    company_id, wallet_id = _ready(
        client, admin, app, fake, tmp_path, "ing-unknown-field@example.com"
    )
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-unk", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    env = _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob)])
    close_calls: list[int] = []
    original_close = multipart_mod.close_upload_files

    async def track_close(uploads):
        close_calls.append(len(list(uploads)))
        await original_close(uploads)

    with patch.object(multipart_mod, "close_upload_files", side_effect=track_close):
        response = client.post(
            f"/api/v1/companies/{company_id}/ingestions",
            data={"envelope": env, "noise": "x"},
            files=[("files", ("p.csv", blob, "application/octet-stream"))],
            headers={"Idempotency-Key": key},
        )
    assert response.status_code == 422
    assert close_calls == [1]


def test_async_event_loop_serves_health_during_ingest_lock(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    asyncio.run(
        _async_event_loop_serves_health_during_ingest_lock(
            client, admin, app, fake, tmp_path
        )
    )


async def _async_event_loop_serves_health_during_ingest_lock(
    client, admin, app, fake, tmp_path
) -> None:
    company_id, wallet_id = _ready(
        client, admin, app, fake, tmp_path, "ing-async-loop@example.com"
    )
    case = DatasetCase("cash", "cash", CASH_HEADER, "ing-async", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    user_id = client.get("/api/v1/auth/me").json()["user"]["id"]
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    env = _envelope(source["id"], key, [_part_meta(1, "cash", "csv", blob)])
    lock_key = f"session-ingest:{user_id}:{key}"
    lock_ready = threading.Event()
    release_lock = threading.Event()
    holder_errors: list[BaseException] = []
    port = os.environ.get("TEST_PG_PORT", "5432")

    def lock_holder() -> None:
        try:
            conn = psycopg.connect(f"postgresql://127.0.0.1:{port}/finpilot_test", autocommit=True)
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_lock(hashtext(%s))", (lock_key,))
            lock_ready.set()
            release_lock.wait(timeout=60)
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (lock_key,))
            conn.close()
        except BaseException as exc:
            holder_errors.append(exc)
        finally:
            release_lock.set()

    holder = threading.Thread(target=lock_holder, daemon=True)
    holder.start()
    assert lock_ready.wait(timeout=15), "advisory lock not acquired"

    transport = ASGITransport(app=app)
    headers = {
        "X-Tenant-Id": client.headers["X-Tenant-Id"],
        "X-CSRF-Token": client.headers["X-CSRF-Token"],
        "Idempotency-Key": key,
    }
    cookies = dict(client.cookies)
    ingest_task: asyncio.Task | None = None
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            ingest_task = asyncio.create_task(
                http.post(
                    f"/api/v1/companies/{company_id}/ingestions",
                    data={"envelope": env},
                    files=[("files", ("p.csv", blob, "application/octet-stream"))],
                    headers=headers,
                    cookies=cookies,
                    timeout=60.0,
                )
            )
            health_seen = False
            for _ in range(80):
                if ingest_task.done():
                    break
                live = await http.get("/health/live", timeout=2.0)
                if live.status_code == 200:
                    health_seen = True
                await asyncio.sleep(0.05)
            assert health_seen, "event loop blocked: /health/live unavailable"
            release_lock.set()
            first = await asyncio.wait_for(ingest_task, timeout=60.0)
            assert first.status_code == 201, first.text
            second = await http.post(
                f"/api/v1/companies/{company_id}/ingestions",
                data={"envelope": env},
                files=[("files", ("p.csv", blob, "application/octet-stream"))],
                headers=headers,
                cookies=cookies,
                timeout=60.0,
            )
            assert second.status_code == 200
            assert first.json() == second.json()
    finally:
        release_lock.set()
        holder.join(timeout=10)
        if ingest_task is not None and not ingest_task.done():
            ingest_task.cancel()
    assert holder_errors == [], holder_errors
    assert _rows(admin, "SELECT count(*) FROM ingestion_deliveries")[0][0] == 1
    assert (
        _rows(
            admin,
            "SELECT count(*) FROM idempotency_records WHERE scope = 'session-ingest'",
        )[0][0]
        == 1
    )


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
