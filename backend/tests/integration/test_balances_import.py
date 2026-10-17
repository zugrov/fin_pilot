import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.services import wallet_service
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.integration.balances_test_util import (
    assert_finpilot_test_database,
    audit_opening_total,
    batch_has_completed_response,
    batch_status,
    opening_counts,
    opening_total,
)
from tests.integration.conftest import (
    freeze,
    latest_link,
    login,
    open_workspace,
    pay,
    register_and_verify,
    token_from_link,
)
from tests.integration.test_import_api import _upload

PERIOD = "date_from=2026-10-01&date_to=2026-10-31"


@pytest.fixture(autouse=True)
def _guard_test_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


@pytest.fixture(autouse=True)
def _balances_import_enabled(app):
    app.state.settings.balances_import_enabled = True

BAL_HEADER = "wallet_code,as_of,balance,currency\n"


def _ready(
    client, admin, app, fake, tmp_path, email: str, *, code: str = "main"
) -> tuple[str, str]:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Balances")
    company = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Фирма", "kind": "company", "timezone": "Europe/Moscow"},
    )
    assert company.status_code == 200, company.text
    company_id = company.json()["id"]
    pay(client, app, fake, 1, "month")
    assert client.post(f"/api/v1/billing/companies/{company_id}/activate").status_code == 200
    wallet = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Расчётный", "type": "bank", "code": code},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert wallet.status_code == 200, wallet.text
    return company_id, wallet.json()["id"]


def _balances_source(client, company_id: str) -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Остатки",
            "type": "file",
            "namespace": "balances",
            "format": "csv",
            "dataset": "balances",
        },
    )
    assert created.status_code == 200, created.text
    return created.json()


def _commit(client, batch_id: str, preview_token: str | None = None):
    headers: dict[str, str] = {}
    if preview_token:
        headers["Preview-Token"] = preview_token
    return client.post(f"/api/v1/imports/{batch_id}/commit", headers=headers)


def _opening_count(admin, wallet_id: str) -> int:
    return opening_counts(admin, wallet_id).get("active", 0)


def _audit_opening_count(admin, wallet_id: str) -> int:
    return audit_opening_total(admin, wallet_id)


def _add_wallet(client, company_id: str, code: str) -> str:
    created = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": code, "type": "bank", "code": code},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def test_balances_preview_does_not_write_opening(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "b-prev@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,1000.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "b1")
    assert uploaded.status_code == 200, uploaded.text
    preview = uploaded.json()
    assert preview["preview_token"]
    assert preview["rows"][0]["intent"] == "create"
    assert _opening_count(admin, wallet_id) == 0
    assert _audit_opening_count(admin, wallet_id) == 0


def test_balances_commit_create_and_unchanged(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "b-create@example.com")
    source = _balances_source(client, company_id)
    client.post(
        f"/api/v1/wallets/{wallet_id}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+03:00", "amount": "1000.00"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    content = BAL_HEADER.encode() + b"main,2026-10-01,1000.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "b2")
    assert uploaded.json()["rows"][0]["intent"] == "unchanged"
    token = uploaded.json()["preview_token"]
    committed = _commit(client, uploaded.json()["id"], token)
    assert committed.status_code == 200, committed.text
    assert committed.json()["rows_committed"] == 0
    assert _opening_count(admin, wallet_id) == 1


def test_balances_zero_amount(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "b-zero@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,0.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "b3")
    token = uploaded.json()["preview_token"]
    assert _commit(client, uploaded.json()["id"], token).status_code == 200
    with admin.connect() as connection:
        amount = connection.execute(
            text(
                "SELECT amount FROM opening_balances "
                "WHERE wallet_id = :wid AND status = 'active'"
            ),
            {"wid": wallet_id},
        ).scalar_one()
    assert str(amount) == "0.00"


def test_balances_invalid_and_duplicate(client, admin, app, fake, tmp_path) -> None:
    company_id, _wallet_id = _ready(client, admin, app, fake, tmp_path, "b-bad@example.com")
    source = _balances_source(client, company_id)
    dup = BAL_HEADER.encode() + b"main,2026-10-01,1.00,RUB\nmain,2026-10-02,2.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], dup, "dup.csv", "b4")
    assert uploaded.json()["commit_blocked"] is True
    dup_commit = _commit(client, uploaded.json()["id"], uploaded.json()["preview_token"])
    assert dup_commit.status_code == 409
    bad = BAL_HEADER.encode() + b"unknown,2026-10-01,1.00,RUB\n"
    uploaded2 = _upload(client, company_id, source["id"], bad, "bad.csv", "b5")
    assert uploaded2.json()["counts"]["invalid"] == 1
    bad_commit = _commit(client, uploaded2.json()["id"], uploaded2.json()["preview_token"])
    assert bad_commit.status_code == 409


def test_balances_stale_token_and_refresh(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "b-stale@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,1000.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "b6")
    old_token = uploaded.json()["preview_token"]
    batch_id = uploaded.json()["id"]
    refreshed = client.post(f"/api/v1/imports/{batch_id}/refresh-preview")
    assert refreshed.status_code == 200, refreshed.text
    new_token = refreshed.json()["preview_token"]
    assert new_token != old_token
    assert _commit(client, batch_id, old_token).status_code == 409
    assert _commit(client, batch_id, new_token).status_code == 200


def test_balances_stale_after_manual_opening(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "b-man@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,1000.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "b7")
    token = uploaded.json()["preview_token"]
    manual = client.post(
        f"/api/v1/wallets/{wallet_id}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+03:00", "amount": "500.00"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert manual.status_code == 200, manual.text
    assert _commit(client, uploaded.json()["id"], token).status_code == 409


def test_balances_completed_replay_snapshot(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "b-replay@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,1000.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "b8")
    token = uploaded.json()["preview_token"]
    first = _commit(client, uploaded.json()["id"], token)
    assert first.status_code == 200
    snapshot = first.json()
    client.post(
        f"/api/v1/wallets/{wallet_id}/opening-balance",
        json={"effective_at": "2026-10-02T00:00:00+03:00", "amount": "1.00"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    replay = _commit(client, uploaded.json()["id"], "stale-token")
    assert replay.status_code == 200
    assert replay.json()["rows_committed"] == snapshot["rows_committed"]
    assert replay.json()["status"] == "completed"


def test_balances_effective_at_timezone(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(
        client, admin, app, fake, tmp_path, "b-tz@example.com", code="tzw"
    )
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"tzw,2026-10-01,10.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "b9")
    token = uploaded.json()["preview_token"]
    assert _commit(client, uploaded.json()["id"], token).status_code == 200
    with admin.connect() as connection:
        effective = connection.execute(
            text(
                "SELECT effective_at FROM opening_balances "
                "WHERE wallet_id = :wid AND status = 'active'"
            ),
            {"wid": wallet_id},
        ).scalar_one()
    assert effective.isoformat().endswith("+03:00") or str(effective).startswith("2026-09-30")


def test_balances_repeat_file_same_batch(client, admin, app, fake, tmp_path) -> None:
    company_id, _ = _ready(client, admin, app, fake, tmp_path, "b-hash@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,1000.00,RUB\n"
    first = _upload(client, company_id, source["id"], content, "balances.csv", "b10a")
    second = _upload(client, company_id, source["id"], content, "balances.csv", "b10b")
    assert first.json()["id"] == second.json()["id"]


def test_balances_invalid_amount_precision(client, admin, app, fake, tmp_path) -> None:
    company_id, _ = _ready(client, admin, app, fake, tmp_path, "b-prec@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,1.001,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "b11")
    assert "invalid_amount_precision" in uploaded.json()["rows"][0]["errors"]


def test_balances_replace_active_replaced_and_audit(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "b-repl@example.com")
    source = _balances_source(client, company_id)
    manual = client.post(
        f"/api/v1/wallets/{wallet_id}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+03:00", "amount": "500.00"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert manual.status_code == 200, manual.text
    content = BAL_HEADER.encode() + b"main,2026-10-01,900.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "b-repl")
    assert uploaded.json()["rows"][0]["intent"] == "replace"
    token = uploaded.json()["preview_token"]
    batch_id = uploaded.json()["id"]
    committed = _commit(client, batch_id, token)
    assert committed.status_code == 200, committed.text
    counts = opening_counts(admin, wallet_id)
    assert counts.get("active", 0) == 1
    assert counts.get("replaced", 0) == 1
    assert opening_total(admin, wallet_id) == 2
    assert audit_opening_total(admin, wallet_id) == 2


def test_balances_currency_mismatch(client, admin, app, fake, tmp_path) -> None:
    company_id, _ = _ready(client, admin, app, fake, tmp_path, "b-cur@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,1.00,USD\n"
    uploaded = _upload(client, company_id, source["id"], content, "badcur.csv", "b-cur")
    assert "currency_mismatch" in uploaded.json()["rows"][0]["errors"]
    bad_commit = _commit(client, uploaded.json()["id"], uploaded.json()["preview_token"])
    assert bad_commit.status_code == 409


def test_balances_invalid_date(client, admin, app, fake, tmp_path) -> None:
    company_id, _ = _ready(client, admin, app, fake, tmp_path, "b-date@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,not-a-date,1.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "baddate.csv", "b-date")
    assert "invalid_date" in uploaded.json()["rows"][0]["errors"]


def test_balances_refresh_completed_is_409(client, admin, app, fake, tmp_path) -> None:
    company_id, _ = _ready(client, admin, app, fake, tmp_path, "b-refc@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,10.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "b-refc")
    token = uploaded.json()["preview_token"]
    batch_id = uploaded.json()["id"]
    assert _commit(client, batch_id, token).status_code == 200
    refresh = client.post(f"/api/v1/imports/{batch_id}/refresh-preview")
    assert refresh.status_code == 409


def test_balances_concurrent_commit_same_batch(client, admin, app, fake, tmp_path) -> None:
    email = "b-conc@example.com"
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, email)
    tenant = client.headers["X-Tenant-Id"]
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,100.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "b-conc")
    batch_id = uploaded.json()["id"]
    token = uploaded.json()["preview_token"]
    results: list[int] = []
    start = threading.Barrier(2)

    def worker() -> None:
        worker_client = TestClient(app, raise_server_exceptions=False)
        login(worker_client, email)
        worker_client.headers["X-Tenant-Id"] = tenant
        start.wait(timeout=10)
        response = _commit(worker_client, batch_id, token)
        results.append(response.status_code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert len(results) == 2
    assert results.count(200) == 1
    assert 409 in results
    assert opening_total(admin, wallet_id) == 1
    assert batch_status(admin, batch_id) == "completed"


def test_balances_overlapping_batches_second_stale(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "b-over@example.com")
    source = _balances_source(client, company_id)
    first = _upload(
        client,
        company_id,
        source["id"],
        BAL_HEADER.encode() + b"main,2026-10-01,100.00,RUB\n",
        "a.csv",
        "b-over-a",
    )
    second = _upload(
        client,
        company_id,
        source["id"],
        BAL_HEADER.encode() + b"main,2026-10-02,200.00,RUB\n",
        "b.csv",
        "b-over-b",
    )
    token_a = first.json()["preview_token"]
    token_b = second.json()["preview_token"]
    assert _commit(client, first.json()["id"], token_a).status_code == 200
    stale = _commit(client, second.json()["id"], token_b)
    assert stale.status_code == 409
    assert opening_total(admin, wallet_id) == 1


def test_balances_mid_batch_fault_rolls_back(
    client, admin, app, fake, tmp_path, monkeypatch
) -> None:
    company_id, wallet_main = _ready(client, admin, app, fake, tmp_path, "b-fault@example.com")
    wallet_sec = _add_wallet(client, company_id, "sec")
    source = _balances_source(client, company_id)
    content = (
        BAL_HEADER.encode()
        + b"main,2026-10-01,10.00,RUB\nsec,2026-10-01,20.00,RUB\n"
    )
    uploaded = _upload(client, company_id, source["id"], content, "two.csv", "b-fault")
    batch_id = uploaded.json()["id"]
    token = uploaded.json()["preview_token"]
    original = wallet_service.set_opening_balance
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("simulated mid-batch fault")
        return original(*args, **kwargs)

    monkeypatch.setattr(wallet_service, "set_opening_balance", flaky)
    safe = TestClient(app, raise_server_exceptions=False)
    login(safe, "b-fault@example.com")
    safe.headers["X-Tenant-Id"] = client.headers["X-Tenant-Id"]
    response = _commit(safe, batch_id, token)
    assert response.status_code >= 500
    assert opening_total(admin, wallet_main) == 0
    assert opening_total(admin, wallet_sec) == 0
    assert audit_opening_total(admin, wallet_main) == 0
    assert batch_status(admin, batch_id) != "completed"
    assert not batch_has_completed_response(admin, batch_id)


def test_balances_two_tenant_isolation(client, admin, app, fake, tmp_path) -> None:
    company_id, _ = _ready(client, admin, app, fake, tmp_path, "b-iso-a@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,1.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "iso.csv", "b-iso")
    batch_id = uploaded.json()["id"]
    token = uploaded.json()["preview_token"]
    foreign = TestClient(app)
    register_and_verify(foreign, admin, "b-iso-b@example.com")
    login(foreign, "b-iso-b@example.com")
    open_workspace(foreign, "Чужой")
    hidden = _commit(foreign, batch_id, token)
    assert hidden.status_code == 404


def test_balances_csrf_denied_on_commit_and_refresh(client, admin, app, fake, tmp_path) -> None:
    company_id, _ = _ready(client, admin, app, fake, tmp_path, "b-csrf@example.com")
    source = _balances_source(client, company_id)
    uploaded = _upload(
        client,
        company_id,
        source["id"],
        BAL_HEADER.encode() + b"main,2026-10-01,1.00,RUB\n",
        "csrf.csv",
        "b-csrf",
    )
    batch_id = uploaded.json()["id"]
    token = uploaded.json()["preview_token"]
    saved = client.headers.pop("X-CSRF-Token")
    try:
        denied_commit = client.post(
            f"/api/v1/imports/{batch_id}/commit", headers={"Preview-Token": token}
        )
        assert denied_commit.status_code == 403
        assert client.post(f"/api/v1/imports/{batch_id}/refresh-preview").status_code == 403
    finally:
        client.headers["X-CSRF-Token"] = saved


def test_balances_operator_and_paid_through_guards(client, admin, app, fake, tmp_path) -> None:
    company_id, _ = _ready(client, admin, app, fake, tmp_path, "b-boss@example.com")
    tenant = client.headers["X-Tenant-Id"]
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,1.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "perm.csv", "b-perm")
    batch_id = uploaded.json()["id"]
    token = uploaded.json()["preview_token"]
    invited = client.post(
        f"/api/v1/workspaces/{tenant}/invitations",
        json={"email": "b-op@example.com", "role": "operator"},
    )
    assert invited.status_code == 200, invited.text
    invite_token = token_from_link(latest_link(admin))
    guest = TestClient(app)
    register_and_verify(guest, admin, "b-op@example.com", name="Оператор")
    login(guest, "b-op@example.com")
    accepted = guest.post("/api/v1/auth/invitations/accept", json={"token": invite_token})
    assert accepted.status_code == 200
    guest.headers["X-Tenant-Id"] = tenant
    logged = guest.get("/api/v1/auth/me").json()
    granted = client.post(
        f"/api/v1/workspaces/{tenant}/company-access",
        json={"user_id": logged["user"]["id"], "company_id": company_id},
    )
    assert granted.status_code == 200, granted.text
    assert _commit(guest, batch_id, token).status_code == 403
    assert guest.post(f"/api/v1/imports/{batch_id}/refresh-preview").status_code == 403
    assert _commit(client, batch_id, token).status_code == 200
    pending = _upload(client, company_id, source["id"], content, "perm2.csv", "b-perm2")
    pending_id = pending.json()["id"]
    pending_token = pending.json()["preview_token"]
    end = client.get("/api/v1/billing/subscription").json()["paid_through"]
    freeze(app, datetime.fromisoformat(end) + timedelta(seconds=1))
    login(client, "b-boss@example.com")
    client.headers["X-Tenant-Id"] = tenant
    assert _commit(client, pending_id, pending_token).status_code == 402
    assert client.post(f"/api/v1/imports/{pending_id}/refresh-preview").status_code == 402
    replay = _commit(client, batch_id, token)
    assert replay.status_code == 402


def test_balances_stale_on_timezone_and_code_change(
    client, admin, app, fake, tmp_path
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "b-stctx@example.com")
    source = _balances_source(client, company_id)
    uploaded = _upload(
        client,
        company_id,
        source["id"],
        BAL_HEADER.encode() + b"main,2026-10-01,50.00,RUB\n",
        "ctx.csv",
        "b-stctx",
    )
    token = uploaded.json()["preview_token"]
    batch_id = uploaded.json()["id"]
    with admin.begin() as connection:
        connection.execute(
            text("UPDATE companies SET timezone = 'Asia/Yekaterinburg' WHERE id = :id"),
            {"id": company_id},
        )
    assert _commit(client, batch_id, token).status_code == 409
    token = client.post(f"/api/v1/imports/{batch_id}/refresh-preview").json()["preview_token"]
    with admin.begin() as connection:
        connection.execute(
            text("UPDATE companies SET timezone = 'Europe/Moscow' WHERE id = :id"),
            {"id": company_id},
        )
        connection.execute(
            text("UPDATE wallets SET code = 'renamed' WHERE id = :id"),
            {"id": wallet_id},
        )
    assert _commit(client, batch_id, token).status_code == 409


def test_balances_dashboard_input_revision(client, admin, app, fake, tmp_path) -> None:
    freeze(app, datetime(2026, 10, 16, 12, tzinfo=UTC))
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "b-dash@example.com")
    before = client.get(f"/api/v1/companies/{company_id}/dashboard?{PERIOD}")
    assert before.status_code == 200, before.text
    rev_before = before.json()["input_revision"]
    source = _balances_source(client, company_id)
    uploaded = _upload(
        client,
        company_id,
        source["id"],
        BAL_HEADER.encode() + b"main,2026-10-01,25000.00,RUB\n",
        "dash.csv",
        "b-dash",
    )
    token = uploaded.json()["preview_token"]
    assert _commit(client, uploaded.json()["id"], token).status_code == 200
    after = client.get(f"/api/v1/companies/{company_id}/dashboard?{PERIOD}")
    assert after.status_code == 200, after.text
    assert after.json()["values"]["cash_total"] == "25000.00"
    assert after.json()["input_revision"] != rev_before
