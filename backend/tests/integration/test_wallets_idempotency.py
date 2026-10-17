import threading
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from app.errors import AppError
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.integration.conftest import freeze, login, open_workspace, pay, register_and_verify
from tests.integration.test_cash import _anchor, _ready


def _wallet(
    client, company_id: str, name: str = "Расчётный", key: str | None = None, **extra
) -> dict:
    payload = {"name": name, "type": "bank", "availability_type": "spendable"}
    payload.update(extra)
    headers = {"Idempotency-Key": key or uuid4().hex}
    created = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json=payload,
        headers=headers,
    )
    assert created.status_code == 200, created.text
    return created.json()


def _audit_count(admin, action: str) -> int:
    with admin.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM audit_log WHERE action = :action"),
                {"action": action},
            ).scalar_one()
        )


def _wallet_count(admin) -> int:
    with admin.connect() as connection:
        return int(connection.execute(text("SELECT count(*) FROM wallets")).scalar_one())


def _active_openings(admin, wallet_id: str) -> int:
    with admin.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM opening_balances "
                    "WHERE wallet_id = :wid AND status = 'active'"
                ),
                {"wid": wallet_id},
            ).scalar_one()
        )


def _all_openings(admin, wallet_id: str) -> int:
    with admin.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM opening_balances WHERE wallet_id = :wid"),
                {"wid": wallet_id},
            ).scalar_one()
        )


def _idempotency_pending(admin, key: str) -> int:
    with admin.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM idempotency_records "
                    "WHERE idempotency_key = :key AND response_body->>'pending' = 'true'"
                ),
                {"key": key},
            ).scalar_one()
        )


def test_wallet_create_idempotent_replay_no_extra_audit(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "idem-wallet@example.com")
    before = _audit_count(admin, "wallet_created")
    key = "wallet-create-once"
    first = _wallet(client, company_id, code="main", key=key)
    second = _wallet(client, company_id, code="main", key=key)
    assert first["id"] == second["id"]
    assert first.get("active_opening") is None
    assert _audit_count(admin, "wallet_created") == before + 1
    assert _wallet_count(admin) == 1


def test_wallet_create_idempotent_payload_conflict(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "idem-conflict@example.com")
    key = "wallet-conflict"
    first = _wallet(client, company_id, code="a", key=key)
    clash = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Другой", "type": "bank", "code": "b"},
        headers={"Idempotency-Key": key},
    )
    assert clash.status_code == 409
    assert clash.json()["code"] == "idempotency_conflict"
    assert _wallet_count(admin) == 1
    listed = client.get(f"/api/v1/companies/{company_id}/wallets").json()["wallets"]
    assert len(listed) == 1
    assert listed[0]["id"] == first["id"]
    assert listed[0]["code"] == "a"


def test_wallet_create_same_key_different_company_conflict(client, admin, app, fake) -> None:
    register_and_verify(client, admin, "two-co@example.com")
    login(client, "two-co@example.com")
    tenant_id = open_workspace(client, "Две")
    pay(client, app, fake, 2, "month")
    alpha = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "А", "kind": "company"},
    )
    beta = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Б", "kind": "company"},
    )
    assert alpha.status_code == beta.status_code == 200
    for row in (alpha.json(), beta.json()):
        assert client.post(f"/api/v1/billing/companies/{row['id']}/activate").status_code == 200
    key = "shared-wallet-key"
    _wallet(client, alpha.json()["id"], code="a", key=key)
    clash = client.post(
        f"/api/v1/companies/{beta.json()['id']}/wallets",
        json={"name": "Бeta", "type": "bank", "code": "b"},
        headers={"Idempotency-Key": key},
    )
    assert clash.status_code == 409
    assert clash.json()["code"] == "idempotency_conflict"
    assert _wallet_count(admin) == 1


def test_wallet_create_duplicate_code(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "dup-code@example.com")
    _wallet(client, company_id, code="main", key="w1")
    dup = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Второй", "type": "bank", "code": "main"},
        headers={"Idempotency-Key": "w2"},
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "duplicate_wallet_code"


def test_wallet_create_requires_idempotency_key(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "no-key@example.com")
    missing = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "X", "type": "bank"},
    )
    assert missing.status_code == 400


def test_opening_idempotent_payload_conflict(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "open-conflict@example.com")
    wallet = _wallet(client, company_id, code="main", key="w-oc")
    key = "opening-conflict"
    body = {"effective_at": "2026-10-01T00:00:00+00:00", "amount": "1000.00"}
    first = client.post(
        f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200, first.text
    clash = client.post(
        f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+00:00", "amount": "2000.00"},
        headers={"Idempotency-Key": key},
    )
    assert clash.status_code == 409
    assert clash.json()["code"] == "idempotency_conflict"
    assert _active_openings(admin, wallet["id"]) == 1
    row = client.get(f"/api/v1/companies/{company_id}/wallets").json()["wallets"][0]
    assert row["active_opening"]["amount"] == "1000.00"


def test_opening_idempotent_replay(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "idem-open@example.com")
    wallet = _wallet(client, company_id, code="main", key="w-open")
    key = "opening-once"
    body = {"effective_at": "2026-10-01T00:00:00+00:00", "amount": "100000.00"}
    headers = {"Idempotency-Key": key}
    first = client.post(
        f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json=body,
        headers=headers,
    )
    assert first.status_code == 200, first.text
    before = _audit_count(admin, "opening_balance_set")
    second = client.post(
        f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json=body,
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]
    assert _audit_count(admin, "opening_balance_set") == before
    assert _active_openings(admin, wallet["id"]) == 1
    total_after = _all_openings(admin, wallet["id"])
    third = client.post(
        f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json=body,
        headers=headers,
    )
    assert third.status_code == 200, third.text
    assert _all_openings(admin, wallet["id"]) == total_after


def test_opening_replace_new_key_keeps_one_active_and_replaced(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "replace-open@example.com")
    wallet = _wallet(client, company_id, code="main", key="w-rep")
    _anchor(client, wallet["id"], "1000.00", key="open-a")
    replaced = client.post(
        f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+00:00", "amount": "2000.00"},
        headers={"Idempotency-Key": "open-b"},
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["id"] != wallet["id"]
    assert _active_openings(admin, wallet["id"]) == 1
    listed = client.get(f"/api/v1/companies/{company_id}/wallets")
    row = next(item for item in listed.json()["wallets"] if item["id"] == wallet["id"])
    assert row["active_opening"]["amount"] == "2000.00"
    with admin.connect() as connection:
        replaced = connection.execute(
            text(
                "SELECT count(*) FROM opening_balances "
                "WHERE wallet_id = :wid AND status = 'replaced'"
            ),
            {"wid": wallet["id"]},
        ).scalar_one()
    assert int(replaced) == 1


def test_idempotency_record_not_pending_after_success(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "no-pending@example.com")
    key = "pending-check"
    _wallet(client, company_id, code="main", key=key)
    with admin.connect() as connection:
        pending = connection.execute(
            text(
                "SELECT count(*) FROM idempotency_records "
                "WHERE idempotency_key = :key AND response_body->>'pending' = 'true'"
            ),
            {"key": key},
        ).scalar_one()
    assert int(pending) == 0


def test_opening_replay_foreign_wallet_blocked(client, admin, app, fake) -> None:
    _ready(client, admin, app, fake, "home-open@example.com")
    other = TestClient(app)
    _tenant, company_id = _ready(other, admin, app, fake, "away-open@example.com")
    wallet = _wallet(other, company_id, code="x", key="w-away")
    key = "shared-opening"
    body = {"effective_at": "2026-10-01T00:00:00+00:00", "amount": "1.00"}
    opened = other.post(
        f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert opened.status_code == 200, opened.text
    stolen = client.post(
        f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert stolen.status_code == 404


def test_wallet_list_includes_active_opening(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "list-open@example.com")
    wallet = _wallet(client, company_id, code="main", key="w-list")
    _anchor(client, wallet["id"], "0.00", key="o-list")
    rows = client.get(f"/api/v1/companies/{company_id}/wallets").json()["wallets"]
    item = next(row for row in rows if row["id"] == wallet["id"])
    assert item["active_opening"]["amount"] == "0.00"
    assert "2026-10-01" in item["active_opening"]["effective_at"]
    effective = item["active_opening"]["effective_at"]
    assert "+" in effective or "-" in effective[-6:]


def test_opening_replay_simulates_lost_response(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "lost-open@example.com")
    wallet = _wallet(client, company_id, code="main", key="w-lost")
    key = "lost-opening-key"
    body = {"effective_at": "2026-10-01T00:00:00+00:00", "amount": "500.00"}
    first = client.post(
        f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200, first.text
    replay = client.post(
        f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert _active_openings(admin, wallet["id"]) == 1


def test_concurrent_wallet_create_same_key(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "race-wallet@example.com")
    key = "race-wallet-key"
    barrier = threading.Barrier(2)
    results: list[dict] = []
    errors: list[Exception] = []

    def worker() -> None:
        worker_client = TestClient(app)
        login(worker_client, "race-wallet@example.com")
        worker_client.headers["X-Tenant-Id"] = _tenant
        try:
            barrier.wait(timeout=5)
            response = worker_client.post(
                f"/api/v1/companies/{company_id}/wallets",
                json={"name": "Гонка", "type": "bank", "code": "race"},
                headers={"Idempotency-Key": key},
            )
            results.append({"status": response.status_code, "body": response.json()})
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert errors == []
    ok = [item for item in results if item["status"] == 200]
    assert len(ok) == 2
    assert ok[0]["body"]["id"] == ok[1]["body"]["id"]
    assert _wallet_count(admin) == 1


def test_wallet_create_fault_after_reserve_clean_retry(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "fault-wallet@example.com")
    key = "fault-wallet-key"
    audit_before = _audit_count(admin, "wallet_created")
    wallets_before = _wallet_count(admin)
    payload = {"name": "Сбой", "type": "bank", "code": "fault-code"}
    with patch(
        "app.services.wallet_service.create_wallet",
        side_effect=AppError(500, "injected_fault", "injected fault"),
    ):
        failed = client.post(
            f"/api/v1/companies/{company_id}/wallets",
            json=payload,
            headers={"Idempotency-Key": key},
        )
    assert failed.status_code == 500
    assert _wallet_count(admin) == wallets_before
    assert _audit_count(admin, "wallet_created") == audit_before
    assert _idempotency_pending(admin, key) == 0
    ok = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json=payload,
        headers={"Idempotency-Key": key},
    )
    assert ok.status_code == 200, ok.text
    assert _wallet_count(admin) == wallets_before + 1
    assert _idempotency_pending(admin, key) == 0


def test_opening_fault_after_idempotency_reserve_keeps_active(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "fault-open@example.com")
    wallet = _wallet(client, company_id, code="main", key="w-fault-open")
    _anchor(client, wallet["id"], "1000.00", key="anchor-before-fault")
    key = "fault-opening-key"
    body = {"effective_at": "2026-10-02T00:00:00+00:00", "amount": "2000.00"}
    audit_before = _audit_count(admin, "opening_balance_set")
    total_before = _all_openings(admin, wallet["id"])
    with patch(
        "app.services.wallet_service.set_opening_balance",
        side_effect=AppError(500, "injected_fault", "injected fault"),
    ):
        failed = client.post(
            f"/api/v1/wallets/{wallet['id']}/opening-balance",
            json=body,
            headers={"Idempotency-Key": key},
        )
    assert failed.status_code == 500
    assert _active_openings(admin, wallet["id"]) == 1
    assert _all_openings(admin, wallet["id"]) == total_before
    assert _audit_count(admin, "opening_balance_set") == audit_before
    assert _idempotency_pending(admin, key) == 0
    row = client.get(f"/api/v1/companies/{company_id}/wallets").json()["wallets"][0]
    assert row["active_opening"]["amount"] == "1000.00"
    ok = client.post(
        f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert ok.status_code == 200, ok.text
    listed = client.get(f"/api/v1/companies/{company_id}/wallets").json()["wallets"][0]
    assert listed["active_opening"]["amount"] == "2000.00"


def test_wallet_create_replay_after_paid_through_is_402(client, admin, app, fake) -> None:
    tenant, company_id = _ready(client, admin, app, fake, "replay-paid-wallet@example.com")
    key = "replay-after-paid-wallet"
    payload = {"name": "До оплаты", "type": "bank", "code": "paid-replay"}
    first = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json=payload,
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200, first.text
    end = datetime.fromisoformat(client.get("/api/v1/billing/subscription").json()["paid_through"])
    freeze(app, end + timedelta(seconds=1))
    login(client, "replay-paid-wallet@example.com")
    client.headers["X-Tenant-Id"] = tenant
    replay = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json=payload,
        headers={"Idempotency-Key": key},
    )
    assert replay.status_code == 402
    assert _wallet_count(admin) == 1


def test_opening_replay_after_paid_through_is_402(client, admin, app, fake) -> None:
    tenant, company_id = _ready(client, admin, app, fake, "replay-paid-open@example.com")
    wallet = _wallet(client, company_id, code="main", key="w-paid-replay")
    key = "replay-after-paid-opening"
    body = {"effective_at": "2026-10-01T00:00:00+00:00", "amount": "500.00"}
    first = client.post(
        f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200, first.text
    end = datetime.fromisoformat(client.get("/api/v1/billing/subscription").json()["paid_through"])
    freeze(app, end + timedelta(seconds=1))
    login(client, "replay-paid-open@example.com")
    client.headers["X-Tenant-Id"] = tenant
    replay = client.post(
        f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert replay.status_code == 402
    assert _active_openings(admin, wallet["id"]) == 1
