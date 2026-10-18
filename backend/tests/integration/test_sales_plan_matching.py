import json
import threading
from datetime import UTC, datetime
from uuid import uuid4

from app.services.cash_service import request_hash
from app.services.revenue_service import CREATE_SCOPE as REVENUE_CREATE_SCOPE
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.integration.conftest import login, open_workspace, pay, register_and_verify
from tests.integration.test_revenue_api import _cash, _ready, _wallet


def _sale_body(**extra):
    body = {
        "recognition_date": "2026-10-10",
        "document_number": "15",
        "amount_ex_vat": "100000.00",
        "vat_amount": "20000.00",
        "amount_inc_vat": "120000.00",
        "entry_type": "sale",
        "vat_basis": "net",
    }
    body.update(extra)
    return body


def _create_sale(client, company_id: str, key: str, **extra) -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json=_sale_body(**extra),
        headers={"Idempotency-Key": key},
    )
    assert created.status_code == 200, created.text
    return created.json()


def _plan(client, company_id: str, key: str, amount: str = "100000.00", **extra) -> dict:
    body = {
        "direction": "out",
        "amount": amount,
        "due_date": extra.pop("due_date", "2026-10-15"),
        "expected_date": extra.pop("expected_date", "2026-10-15"),
    }
    body.update(extra)
    created = client.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert created.status_code == 200, created.text
    return created.json()


def _revenue_match(client, company_id: str, entry_id: str, cash_id: str, amount: str, key: str):
    return client.post(
        "/api/v1/revenue-cash-matches",
        json={
            "company_id": company_id,
            "revenue_entry_id": entry_id,
            "cash_transaction_id": cash_id,
            "amount": amount,
        },
        headers={"Idempotency-Key": key},
    )


def _plan_match(client, company_id: str, event_id: str, cash_id: str, amount: str, key: str):
    return client.post(
        "/api/v1/payment-matches",
        json={
            "company_id": company_id,
            "event_id": event_id,
            "cash_transaction_id": cash_id,
            "amount": amount,
        },
        headers={"Idempotency-Key": key},
    )


def _match_count(admin, table: str) -> int:
    with admin.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def _audit_count(admin, action: str) -> int:
    with admin.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM audit_log WHERE action = :action"),
                {"action": action},
            ).scalar_one()
        )


def _revenue_entry_count(admin) -> int:
    with admin.connect() as connection:
        return int(connection.execute(text("SELECT count(*) FROM revenue_entries")).scalar_one())


def _plan_event_count(admin) -> int:
    with admin.connect() as connection:
        return int(
            connection.execute(text("SELECT count(*) FROM planned_cash_events")).scalar_one()
        )


def test_revenue_create_replay_and_read_aggregates(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-list@example.com")
    key = "rev-create-once"
    first = _create_sale(
        client,
        company_id,
        key,
        external_id="ext-1",
        document_number="DOC-1",
    )
    audit_before = _audit_count(admin, "revenue_created")
    second = _create_sale(client, company_id, key, external_id="ext-1", document_number="DOC-1")
    assert first["id"] == second["id"]
    assert first["company_id"] == company_id
    assert _revenue_entry_count(admin) == 1
    assert _audit_count(admin, "revenue_created") == audit_before
    assert first["external_id"] == "ext-1"
    listed = client.get(f"/api/v1/companies/{company_id}/revenue")
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json()["entries"] if item["id"] == first["id"])
    assert row["matched_amount"] == "0.00"
    assert row["unallocated_amount"] == "120000.00"
    assert row["match_links"] == []


def test_revenue_create_same_key_other_company_conflict(
    client, admin, app, fake, tmp_path
) -> None:
    register_and_verify(client, admin, "r31-two@example.com")
    login(client, "r31-two@example.com")
    tenant_id = open_workspace(client, "Две продажи")
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
    key = "shared-revenue-key"
    _create_sale(client, alpha.json()["id"], key)
    clash = client.post(
        f"/api/v1/companies/{beta.json()['id']}/revenue",
        json=_sale_body(),
        headers={"Idempotency-Key": key},
    )
    assert clash.status_code == 409
    assert clash.json()["code"] == "idempotency_conflict"


def test_revenue_create_payload_conflict(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-conf@example.com")
    key = "rev-conflict"
    first = _create_sale(client, company_id, key)
    clash = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json=_sale_body(document_number="other"),
        headers={"Idempotency-Key": key},
    )
    assert clash.status_code == 409
    assert clash.json()["code"] == "idempotency_conflict"
    assert _revenue_entry_count(admin) == 1
    assert first["id"] == _create_sale(client, company_id, key)["id"]


def test_revenue_match_replay_and_partial_aggregates(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-match@example.com")
    wallet = _wallet(client, company_id)
    cash = _cash(client, company_id, wallet["id"], "in", "80000.00")
    sale = _create_sale(client, company_id, "sale-partial")
    key = "match-partial"
    first = _revenue_match(client, company_id, sale["id"], cash["id"], "50000.00", key)
    assert first.status_code == 200, first.text
    audit_before = _audit_count(admin, "revenue_matched")
    replay = _revenue_match(client, company_id, sale["id"], cash["id"], "50000.00", key)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert _match_count(admin, "revenue_cash_matches") == 1
    assert _audit_count(admin, "revenue_matched") == audit_before
    listed = client.get(f"/api/v1/companies/{company_id}/revenue").json()["entries"]
    row = next(item for item in listed if item["id"] == sale["id"])
    assert row["matched_amount"] == "50000.00"
    assert row["unallocated_amount"] == "70000.00"
    assert len(row["match_links"]) == 1
    tx = client.get(
        f"/api/v1/companies/{company_id}/transactions",
        params={"status": "posted"},
    ).json()["transactions"]
    cash_row = next(item for item in tx if item["id"] == cash["id"])
    assert cash_row["revenue_matched"] == "50000.00"
    assert cash_row["revenue_unallocated"] == "30000.00"


def test_sale_match_rejects_non_in_rub(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-dir@example.com")
    wallet = _wallet(client, company_id)
    outflow = _cash(client, company_id, wallet["id"], "out", "50000.00")
    sale = _create_sale(client, company_id, "sale-dir")
    bad = _revenue_match(
        client, company_id, sale["id"], outflow["id"], "10000.00", uuid4().hex
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "validation_error"


def test_match_does_not_change_cash_balance(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-bal@example.com")
    wallet = _wallet(client, company_id)
    cash = _cash(client, company_id, wallet["id"], "in", "60000.00")
    sale = _create_sale(client, company_id, "sale-bal")
    before = client.get(f"/api/v1/companies/{company_id}/cash-summary").json()
    matched = _revenue_match(
        client, company_id, sale["id"], cash["id"], "60000.00", "match-bal"
    )
    assert matched.status_code == 200, matched.text
    after = client.get(f"/api/v1/companies/{company_id}/cash-summary").json()
    assert after["cash_total"] == before["cash_total"]
    assert after.get("cash_in") == before.get("cash_in")
    assert _match_count(admin, "cash_transactions") == 1


def test_plan_create_same_key_other_company_conflict(client, admin, app, fake, tmp_path) -> None:
    register_and_verify(client, admin, "r31-plan2@example.com")
    login(client, "r31-plan2@example.com")
    tenant_id = open_workspace(client, "Два плана")
    pay(client, app, fake, 2, "month")
    alpha = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "А", "kind": "company"},
    )
    beta = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Б", "kind": "company"},
    )
    for row in (alpha.json(), beta.json()):
        assert client.post(f"/api/v1/billing/companies/{row['id']}/activate").status_code == 200
    key = "shared-plan-key"
    _plan(client, alpha.json()["id"], key)
    clash = client.post(
        f"/api/v1/companies/{beta.json()['id']}/planned-cash",
        json={
            "direction": "out",
            "amount": "1000.00",
            "due_date": "2026-10-15",
            "expected_date": "2026-10-15",
        },
        headers={"Idempotency-Key": key},
    )
    assert clash.status_code == 409
    assert clash.json()["code"] == "idempotency_conflict"


def test_plan_match_replay(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-pm@example.com")
    wallet = _wallet(client, company_id)
    paid = _cash(client, company_id, wallet["id"], "out", "40000.00")
    event = _plan(client, company_id, "ev-pm")
    key = "plan-match-once"
    first = _plan_match(client, company_id, event["id"], paid["id"], "40000.00", key)
    assert first.status_code == 200, first.text
    audit_before = _audit_count(admin, "plan_matched")
    replay = _plan_match(client, company_id, event["id"], paid["id"], "40000.00", key)
    assert replay.status_code == 200, replay.text
    assert replay.json()["id"] == first.json()["id"]
    assert _match_count(admin, "payment_matches") == 1
    assert _audit_count(admin, "plan_matched") == audit_before


def test_concurrent_revenue_matches_on_same_cash(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-race@example.com")
    wallet = _wallet(client, company_id)
    cash = _cash(client, company_id, wallet["id"], "in", "100000.00")
    sale_a = _create_sale(client, company_id, "race-a", amount_inc_vat="120000.00")
    sale_b = _create_sale(client, company_id, "race-b", amount_inc_vat="120000.00")
    barrier = threading.Barrier(2)
    results: list[int] = []

    def worker(entry_id: str, key: str) -> None:
        worker_client = TestClient(app)
        login(worker_client, "r31-race@example.com")
        worker_client.headers["X-Tenant-Id"] = _tenant
        barrier.wait(timeout=5)
        response = _revenue_match(
            worker_client, company_id, entry_id, cash["id"], "70000.00", key
        )
        results.append(response.status_code)

    threads = [
        threading.Thread(target=worker, args=(sale_a["id"], "race-key-a")),
        threading.Thread(target=worker, args=(sale_b["id"], "race-key-b")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(results) == [200, 422]
    assert _match_count(admin, "revenue_cash_matches") == 1
    tx = client.get(
        f"/api/v1/companies/{company_id}/transactions",
        params={"status": "posted"},
    ).json()["transactions"]
    cash_row = next(item for item in tx if item["id"] == cash["id"])
    assert cash_row["revenue_unallocated"] == "30000.00"


def test_four_actions_require_idempotency_key(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-keys@example.com")
    wallet = _wallet(client, company_id)
    cash = _cash(client, company_id, wallet["id"], "in", "1000.00")
    missing_rev = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json=_sale_body(amount_inc_vat="1000.00", amount_ex_vat="1000.00", vat_amount="0.00"),
    )
    assert missing_rev.status_code == 400
    missing_plan = client.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json={
            "direction": "out",
            "amount": "100.00",
            "due_date": "2026-10-15",
            "expected_date": "2026-10-15",
        },
    )
    assert missing_plan.status_code == 400
    sale = _create_sale(
        client,
        company_id,
        "k-sale",
        amount_inc_vat="1000.00",
        amount_ex_vat="1000.00",
        vat_amount="0.00",
    )
    event = _plan(client, company_id, "k-plan", amount="100.00")
    rev_no_key = _revenue_match(client, company_id, sale["id"], cash["id"], "100.00", "")
    assert rev_no_key.status_code == 400
    assert (
        _plan_match(client, company_id, event["id"], cash["id"], "50.00", "").status_code == 400
    )


def test_plan_create_replay_and_payload_conflict(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-plcr@example.com")
    key = "plan-create-once"
    audit_before = _audit_count(admin, "plan_created")
    first = _plan(client, company_id, key, amount="50000.00")
    second = _plan(client, company_id, key, amount="50000.00")
    assert first["id"] == second["id"]
    assert _plan_event_count(admin) == 1
    assert _audit_count(admin, "plan_created") == audit_before + 1
    clash = client.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json={
            "direction": "out",
            "amount": "51000.00",
            "due_date": "2026-10-15",
            "expected_date": "2026-10-15",
        },
        headers={"Idempotency-Key": key},
    )
    assert clash.status_code == 409
    assert _plan_event_count(admin) == 1


def test_revenue_match_payload_conflict(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-rmc@example.com")
    wallet = _wallet(client, company_id)
    cash = _cash(client, company_id, wallet["id"], "in", "50000.00")
    sale = _create_sale(client, company_id, "sale-rmc")
    key = "rev-match-conflict"
    first = _revenue_match(client, company_id, sale["id"], cash["id"], "10000.00", key)
    assert first.status_code == 200, first.text
    clash = _revenue_match(client, company_id, sale["id"], cash["id"], "20000.00", key)
    assert clash.status_code == 409
    assert _match_count(admin, "revenue_cash_matches") == 1


def test_plan_match_payload_conflict(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-pmc@example.com")
    wallet = _wallet(client, company_id)
    paid = _cash(client, company_id, wallet["id"], "out", "50000.00")
    event = _plan(client, company_id, "ev-pmc")
    key = "plan-match-conflict"
    first = _plan_match(client, company_id, event["id"], paid["id"], "10000.00", key)
    assert first.status_code == 200, first.text
    clash = _plan_match(client, company_id, event["id"], paid["id"], "20000.00", key)
    assert clash.status_code == 409
    assert _match_count(admin, "payment_matches") == 1


def test_concurrent_plan_matches_on_same_cash(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-prace@example.com")
    wallet = _wallet(client, company_id)
    cash = _cash(client, company_id, wallet["id"], "out", "100000.00")
    event_a = _plan(client, company_id, "prace-a", amount="120000.00")
    event_b = _plan(client, company_id, "prace-b", amount="120000.00")
    barrier = threading.Barrier(2)
    results: list[int] = []

    def worker(event_id: str, key: str) -> None:
        worker_client = TestClient(app)
        login(worker_client, "r31-prace@example.com")
        worker_client.headers["X-Tenant-Id"] = _tenant
        barrier.wait(timeout=5)
        response = _plan_match(worker_client, company_id, event_id, cash["id"], "70000.00", key)
        results.append(response.status_code)

    threads = [
        threading.Thread(target=worker, args=(event_a["id"], "prace-key-a")),
        threading.Thread(target=worker, args=(event_b["id"], "prace-key-b")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(results) == [200, 422]
    assert _match_count(admin, "payment_matches") == 1


def test_concurrent_revenue_matches_same_entry_different_cash(
    client, admin, app, fake, tmp_path
) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-erace@example.com")
    wallet = _wallet(client, company_id)
    cash_a = _cash(client, company_id, wallet["id"], "in", "60000.00")
    cash_b = _cash(client, company_id, wallet["id"], "in", "60000.00", description="второй")
    sale = _create_sale(
        client,
        company_id,
        "erace-sale",
        amount_inc_vat="100000.00",
        amount_ex_vat="83333.33",
        vat_amount="16666.67",
    )
    barrier = threading.Barrier(2)
    results: list[int] = []

    def worker(cash_id: str, key: str) -> None:
        worker_client = TestClient(app)
        login(worker_client, "r31-erace@example.com")
        worker_client.headers["X-Tenant-Id"] = _tenant
        barrier.wait(timeout=5)
        response = _revenue_match(
            worker_client, company_id, sale["id"], cash_id, "60000.00", key
        )
        results.append(response.status_code)

    threads = [
        threading.Thread(target=worker, args=(cash_a["id"], "erace-a")),
        threading.Thread(target=worker, args=(cash_b["id"], "erace-b")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(results) == [200, 422]
    assert _match_count(admin, "revenue_cash_matches") == 1
    row = next(
        item
        for item in client.get(f"/api/v1/companies/{company_id}/revenue").json()["entries"]
        if item["id"] == sale["id"]
    )
    assert row["matched_amount"] == "60000.00"


def test_legacy_idempotency_replay_without_company_id_is_rejected(
    client, admin, app, fake, tmp_path
) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-legacy@example.com")
    login(client, "r31-legacy@example.com")
    me = client.get("/api/v1/auth/me").json()
    user_id = me["user"]["id"]
    tenant_id = me["memberships"][0]["tenant_id"]
    key = "legacy-revenue-key"
    body = _sale_body(document_number="LEG-1")
    fingerprint = request_hash(
        {
            "company_id": company_id,
            "recognition_date": body["recognition_date"],
            "document_number": body["document_number"],
            "amount_ex_vat": body["amount_ex_vat"],
            "vat_amount": body["vat_amount"],
            "amount_inc_vat": body["amount_inc_vat"],
            "entry_type": body["entry_type"],
            "vat_basis": body["vat_basis"],
            "direction_code": None,
            "counterparty_inn": None,
            "counterparty_name": None,
            "external_id": None,
        }
    )
    legacy_response = {
        "id": str(uuid4()),
        "recognition_date": body["recognition_date"],
        "amount_inc_vat": body["amount_inc_vat"],
        "entry_type": "sale",
        "status": "posted",
    }
    at = datetime.now(UTC)
    with admin.connect() as connection:
        connection.execute(
            text(
                "INSERT INTO idempotency_records "
                "(id, tenant_id, user_id, scope, idempotency_key, request_hash, "
                "status_code, response_body, created_at) "
                "VALUES (:id, :tenant, :user, :scope, :key, :hash, 200, "
                "CAST(:body AS jsonb), :at)"
            ),
            {
                "id": str(uuid4()),
                "tenant": tenant_id,
                "user": user_id,
                "scope": REVENUE_CREATE_SCOPE,
                "key": key,
                "hash": fingerprint,
                "body": json.dumps(legacy_response),
                "at": at,
            },
        )
        connection.commit()
    before = _revenue_entry_count(admin)
    blocked = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "idempotency_conflict"
    assert _revenue_entry_count(admin) == before


def test_legacy_fingerprint_without_company_id_conflicts_with_new_hash(
    client, admin, app, fake, tmp_path
) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "r31-leg2@example.com")
    login(client, "r31-leg2@example.com")
    me = client.get("/api/v1/auth/me").json()
    user_id = me["user"]["id"]
    tenant_id = me["memberships"][0]["tenant_id"]
    key = "legacy-hash-key"
    body = _sale_body()
    old_fingerprint = request_hash(
        {
            "recognition_date": body["recognition_date"],
            "document_number": body["document_number"],
            "amount_ex_vat": body["amount_ex_vat"],
            "vat_amount": body["vat_amount"],
            "amount_inc_vat": body["amount_inc_vat"],
            "entry_type": body["entry_type"],
            "vat_basis": body["vat_basis"],
            "direction_code": None,
            "counterparty_inn": None,
            "counterparty_name": None,
            "external_id": None,
        }
    )
    at = datetime.now(UTC)
    with admin.connect() as connection:
        connection.execute(
            text(
                "INSERT INTO idempotency_records "
                "(id, tenant_id, user_id, scope, idempotency_key, request_hash, "
                "status_code, response_body, created_at) "
                "VALUES (:id, :tenant, :user, :scope, :key, :hash, 200, "
                "'{\"id\": \"00000000-0000-0000-0000-000000000001\"}'::jsonb, :at)"
            ),
            {
                "id": str(uuid4()),
                "tenant": tenant_id,
                "user": user_id,
                "scope": REVENUE_CREATE_SCOPE,
                "key": key,
                "hash": old_fingerprint,
                "at": at,
            },
        )
        connection.commit()
    before = _revenue_entry_count(admin)
    clash = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert clash.status_code == 409
    assert clash.json()["code"] == "idempotency_conflict"
    assert _revenue_entry_count(admin) == before
