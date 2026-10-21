import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.mail_ingress import build_simple_mime
from app.services.mail_quarantine_service import expire_mail_quarantine_entries
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from tests.integration.conftest import (
    freeze,
    login,
    open_workspace,
    register_and_verify,
    token_from_link,
)
from tests.integration.test_mail_ingress import (
    RECEIVED,
    _bundle,
    _counts,
    _ingest,
    _ready,
)

FORBIDDEN_RESPONSE_KEYS = {
    "message_digest",
    "sender_normalized",
    "message_id_header",
    "reviewer_user_id",
    "tenant_id",
    "transport_trust_level",
}


def _enable(app) -> None:
    app.state.settings.mail_quarantine_enabled = True


def _seed_open_entry(client, admin, app, fake, tmp_path, email: str = "mq-api@example.com"):
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable(app)
    raw = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"x",
    )
    _ingest(app, raw, _bundle(tenant_id, company_id, user_id, source_id, raw, uid=201))
    with admin.connect() as connection:
        row = connection.execute(
            text(
                "SELECT id::text FROM mail_quarantine_entries "
                "WHERE company_id = :cid ORDER BY created_at DESC LIMIT 1"
            ),
            {"cid": company_id},
        ).one()
    return tenant_id, company_id, row[0]


def _close(client, company_id: str, entry_id: str, key: str, resolution: str = "dismissed"):
    return client.post(
        f"/api/v1/companies/{company_id}/mail-quarantine/{entry_id}/close",
        json={"resolution": resolution, "note": "ok"},
        headers={"Idempotency-Key": key},
    )


def _assert_no_forbidden_fields(payload: object) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            assert key not in FORBIDDEN_RESPONSE_KEYS
            _assert_no_forbidden_fields(value)
    elif isinstance(payload, list):
        for item in payload:
            _assert_no_forbidden_fields(item)


def test_viewer_reads_and_cannot_close(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, entry_id = _seed_open_entry(
        client, admin, app, fake, tmp_path, "mq-viewer@example.com"
    )
    invited = client.post(
        f"/api/v1/workspaces/{tenant_id}/invitations",
        json={"email": "viewer-mq@example.com", "role": "viewer"},
    )
    assert invited.status_code == 200, invited.text
    with admin.connect() as connection:
        invite_link = connection.execute(
            text(
                "SELECT payload_redacted->>'link' FROM transactional_email_outbox "
                "WHERE type = 'invite' ORDER BY created_at DESC LIMIT 1"
            )
        ).scalar_one()
    token = token_from_link(str(invite_link))
    guest = TestClient(client.app)
    register_and_verify(guest, admin, "viewer-mq@example.com")
    guest_login = login(guest, "viewer-mq@example.com")
    with admin.connect() as connection:
        connection.execute(
            text(
                "UPDATE users SET email_verified_at = COALESCE(email_verified_at, now()) "
                "WHERE normalized_email = :email"
            ),
            {"email": "viewer-mq@example.com"},
        )
        connection.commit()
    accepted = guest.post("/api/v1/auth/invitations/accept", json={"token": token})
    assert accepted.status_code == 200, accepted.text
    guest_user_id = guest_login["user"]["id"]
    granted = client.post(
        f"/api/v1/workspaces/{tenant_id}/company-access",
        json={"user_id": guest_user_id, "company_id": company_id},
    )
    assert granted.status_code == 200, granted.text
    guest.headers["X-Tenant-Id"] = tenant_id
    listed = guest.get(f"/api/v1/companies/{company_id}/mail-quarantine")
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["entries"]) >= 1
    denied = _close(guest, company_id, entry_id, uuid4().hex)
    assert denied.status_code == 403


def test_foreign_tenant_gets_404(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, entry_id = _seed_open_entry(
        client, admin, app, fake, tmp_path, "mq-foreign@example.com"
    )
    outsider = client.__class__(client.app)
    register_and_verify(outsider, admin, "mq-outsider@example.com")
    login(outsider, "mq-outsider@example.com")
    other_tenant = open_workspace(outsider, "Чужое")
    outsider.headers["X-Tenant-Id"] = other_tenant
    missing = outsider.get(
        f"/api/v1/companies/{company_id}/mail-quarantine/{entry_id}"
    )
    assert missing.status_code == 404


def test_unpaid_company_gets_402(client, admin, app, fake, tmp_path) -> None:
    email = "mq-unpaid@example.com"
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Unpaid")
    company = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Без оплаты", "kind": "company"},
    )
    assert company.status_code == 200, company.text
    company_id = company.json()["id"]
    _enable(app)
    blocked = client.get(f"/api/v1/companies/{company_id}/mail-quarantine")
    assert blocked.status_code == 402


def test_unverified_email_gets_403_on_close(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, entry_id = _seed_open_entry(
        client, admin, app, fake, tmp_path, "mq-unver@example.com"
    )
    with admin.connect() as connection:
        connection.execute(
            text("UPDATE users SET email_verified_at = NULL WHERE normalized_email = :email"),
            {"email": "mq-unver@example.com"},
        )
        connection.commit()
    denied = _close(client, company_id, entry_id, uuid4().hex)
    assert denied.status_code == 403


def test_flag_disabled_returns_404(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, entry_id = _seed_open_entry(
        client, admin, app, fake, tmp_path, "mq-flag@example.com"
    )
    app.state.settings.mail_quarantine_enabled = False
    assert client.get(f"/api/v1/companies/{company_id}/mail-quarantine").status_code == 404
    assert (
        client.get(f"/api/v1/companies/{company_id}/mail-quarantine/{entry_id}").status_code
        == 404
    )
    assert _close(client, company_id, entry_id, uuid4().hex).status_code == 404


def test_close_open_and_repeat_conflict(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, entry_id = _seed_open_entry(
        client, admin, app, fake, tmp_path, "mq-close@example.com"
    )
    first = _close(client, company_id, entry_id, uuid4().hex)
    assert first.status_code == 200, first.text
    assert first.json()["entry"]["status"] == "closed"
    second = _close(client, company_id, entry_id, uuid4().hex)
    assert second.status_code == 409


def test_concurrent_close_one_success(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, entry_id = _seed_open_entry(
        client, admin, app, fake, tmp_path, "mq-race-close@example.com"
    )

    def _run(key: str) -> int:
        worker = TestClient(client.app)
        worker.headers.update(client.headers)
        worker.cookies.update(client.cookies)
        return _close(worker, company_id, entry_id, key).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        codes = list(pool.map(_run, (uuid4().hex, uuid4().hex)))
    assert sorted(codes) == [200, 409]


def test_idempotency_replay_and_conflict(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, entry_id = _seed_open_entry(
        client, admin, app, fake, tmp_path, "mq-idem@example.com"
    )
    key = uuid4().hex
    first = _close(client, company_id, entry_id, key)
    assert first.status_code == 200
    replay = _close(client, company_id, entry_id, key)
    assert replay.status_code == 200
    assert replay.json() == first.json()
    conflict = client.post(
        f"/api/v1/companies/{company_id}/mail-quarantine/{entry_id}/close",
        json={"resolution": "escalated", "note": "other"},
        headers={"Idempotency-Key": key},
    )
    assert conflict.status_code == 409


def test_audit_written_once_without_note(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, entry_id = _seed_open_entry(
        client, admin, app, fake, tmp_path, "mq-audit@example.com"
    )
    note = "secret operator note"
    closed = client.post(
        f"/api/v1/companies/{company_id}/mail-quarantine/{entry_id}/close",
        json={"resolution": "dismissed", "note": note},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert closed.status_code == 200
    with admin.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT action, after_redacted::text FROM audit_log "
                "WHERE action = 'mail_quarantine_resolved'"
            )
        ).fetchall()
    assert len(rows) == 1
    assert note not in rows[0][1]
    assert "resolution" in rows[0][1]


def test_pagination_limit_and_status_filter(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, entry_id = _seed_open_entry(
        client, admin, app, fake, tmp_path, "mq-page@example.com"
    )
    too_large = client.get(
        f"/api/v1/companies/{company_id}/mail-quarantine",
        params={"limit": 101},
    )
    assert too_large.status_code == 422
    open_only = client.get(
        f"/api/v1/companies/{company_id}/mail-quarantine",
        params={"status": "open", "limit": 1},
    )
    assert open_only.status_code == 200
    assert len(open_only.json()["entries"]) == 1
    _close(client, company_id, entry_id, uuid4().hex)
    closed_only = client.get(
        f"/api/v1/companies/{company_id}/mail-quarantine",
        params={"status": "closed"},
    )
    assert all(item["status"] == "closed" for item in closed_only.json()["entries"])


def test_expired_entry_cannot_close(client, admin, app, fake, tmp_path) -> None:
    email = "mq-exp@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable(app)
    freeze(app, datetime(2010, 1, 1, tzinfo=UTC))
    raw = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"y",
    )
    _ingest(app, raw, _bundle(tenant_id, company_id, user_id, source_id, raw, uid=202))
    with admin.connect() as connection:
        exp_id = connection.execute(
            text(
                "SELECT id::text FROM mail_quarantine_entries "
                "WHERE company_id = :cid ORDER BY created_at DESC LIMIT 1"
            ),
            {"cid": company_id},
        ).scalar_one()
    worker_engine = create_engine(os.environ["WORKER_DATABASE_URL"])
    worker_session = sessionmaker(bind=worker_engine)()
    try:
        expire_mail_quarantine_entries(
            worker_session,
            before=datetime(2026, 10, 21, tzinfo=UTC),
            limit=50,
        )
        worker_session.commit()
    finally:
        worker_session.close()
    freeze(app, RECEIVED)
    card = client.get(f"/api/v1/companies/{company_id}/mail-quarantine/{exp_id}")
    assert card.status_code == 200
    assert card.json()["entry"]["metadata_allowed"] == {}
    denied = _close(client, company_id, str(exp_id), uuid4().hex)
    assert denied.status_code == 409


def test_response_has_no_forbidden_fields(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, entry_id = _seed_open_entry(
        client, admin, app, fake, tmp_path, "mq-fields@example.com"
    )
    card = client.get(f"/api/v1/companies/{company_id}/mail-quarantine/{entry_id}")
    _assert_no_forbidden_fields(card.json())
    listed = client.get(f"/api/v1/companies/{company_id}/mail-quarantine")
    _assert_no_forbidden_fields(listed.json())


def test_close_does_not_touch_finance_tables(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, entry_id = _seed_open_entry(
        client, admin, app, fake, tmp_path, "mq-side@example.com"
    )
    before = _counts(admin)
    assert _close(client, company_id, entry_id, uuid4().hex).status_code == 200
    assert _counts(admin) == before
