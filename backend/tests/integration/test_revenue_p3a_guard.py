"""FA-R06.1-P3a: guard matches + linked returns ≤ gross sale."""

from __future__ import annotations

import threading
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.integration.conftest import login, open_workspace, pay, register_and_verify
from tests.integration.test_sales_plan_matching import _revenue_match, _wallet
from tests.synthetic_polygon.receivable_harness import (
    _entry_id_by_external_id,
    load_receivable_demo_profile,
)


@pytest.fixture(autouse=True)
def _balances_import_enabled(app):
    app.state.settings.balances_import_enabled = True


def _company(client, admin, app, fake, tmp_path, email: str) -> tuple[str, str]:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "P3a guard")
    pay(client, app, fake, 1, "month")
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "P3a Co", "kind": "company"},
    )
    assert created.status_code == 200, created.text
    company_id = created.json()["id"]
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return tenant_id, company_id


def _cash_in(client, company_id: str, wallet_id: str, amount: str, key: str) -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/transactions",
        json={
            "wallet_id": wallet_id,
            "business_date": "2026-10-15",
            "direction": "in",
            "amount": amount,
            "description": "оплата RD-C",
        },
        headers={"Idempotency-Key": key},
    )
    assert created.status_code == 200, created.text
    return created.json()


def _main_wallet_id(client, company_id: str) -> str:
    listed = client.get(f"/api/v1/companies/{company_id}/wallets")
    assert listed.status_code == 200, listed.text
    return listed.json()["wallets"][0]["id"]


def test_rd_c_match_6000_ok_then_501_returns_422(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _company(client, admin, app, fake, tmp_path, "p3a-rdc@example.com")
    load_receivable_demo_profile(client, company_id)
    sale_id = _entry_id_by_external_id(client, company_id, "rd-r-c-sale")
    wallet_id = _main_wallet_id(client, company_id)
    cash_a = _cash_in(client, company_id, wallet_id, "6000.00", "p3a-cash-a")
    cash_b = _cash_in(client, company_id, wallet_id, "501.00", "p3a-cash-b")
    first = _revenue_match(client, company_id, sale_id, cash_a["id"], "6000.00", "p3a-m-6000")
    assert first.status_code == 200, first.text
    second = _revenue_match(client, company_id, sale_id, cash_b["id"], "501.00", "p3a-m-501")
    assert second.status_code == 422, second.text


def test_relink_return_exceeds_sale_capacity_returns_422(
    client, admin, app, fake, tmp_path
) -> None:
    _tenant, company_id = _company(client, admin, app, fake, tmp_path, "p3a-link@example.com")
    wallet = _wallet(client, company_id)
    sale = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-10",
            "amount_ex_vat": "5000.00",
            "vat_amount": "1000.00",
            "amount_inc_vat": "6000.00",
            "entry_type": "sale",
            "external_id": "sale-cap",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert sale.status_code == 200, sale.text
    sale_id = sale.json()["id"]
    cash = _cash_in(client, company_id, wallet["id"], "5500.00", "p3a-cap-cash")
    matched = _revenue_match(client, company_id, sale_id, cash["id"], "5500.00", "p3a-cap-match")
    assert matched.status_code == 200, matched.text
    ret = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-11",
            "amount_ex_vat": "416.67",
            "vat_amount": "83.33",
            "amount_inc_vat": "500.00",
            "entry_type": "return",
            "external_id": "ret-cap",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert ret.status_code == 200, ret.text
    ret_row = ret.json()
    big = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-12",
            "amount_ex_vat": "833.33",
            "vat_amount": "166.67",
            "amount_inc_vat": "1000.00",
            "entry_type": "return",
            "external_id": "ret-big",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert big.status_code == 200, big.text
    blocked = client.patch(
        f"/api/v1/companies/{company_id}/revenue/{big.json()['id']}/linked-sale",
        json={"linked_sale_entry_id": sale_id, "version": big.json()["version"]},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert blocked.status_code == 422, blocked.text
    ok = client.patch(
        f"/api/v1/companies/{company_id}/revenue/{ret_row['id']}/linked-sale",
        json={"linked_sale_entry_id": sale_id, "version": ret_row["version"]},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert ok.status_code == 200, ok.text


def test_concurrent_return_links_on_same_sale(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id = _company(client, admin, app, fake, tmp_path, "p3a-race@example.com")
    wallet = _wallet(client, company_id)
    sale = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-10",
            "amount_ex_vat": "6666.67",
            "vat_amount": "1333.33",
            "amount_inc_vat": "8000.00",
            "entry_type": "sale",
            "external_id": "race-sale",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert sale.status_code == 200, sale.text
    sale_id = sale.json()["id"]
    cash = _cash_in(client, company_id, wallet["id"], "5000.00", "p3a-race-cash")
    matched = _revenue_match(client, company_id, sale_id, cash["id"], "5000.00", "p3a-race-match")
    assert matched.status_code == 200, matched.text
    ret_a = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-11",
            "amount_ex_vat": "1666.67",
            "vat_amount": "333.33",
            "amount_inc_vat": "2000.00",
            "entry_type": "return",
            "external_id": "race-ret-a",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    ret_b = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-12",
            "amount_ex_vat": "1666.67",
            "vat_amount": "333.33",
            "amount_inc_vat": "2000.00",
            "entry_type": "return",
            "external_id": "race-ret-b",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert ret_a.status_code == 200 and ret_b.status_code == 200
    barrier = threading.Barrier(2)
    results: list[int] = []

    def worker(ret_payload: dict, key: str) -> None:
        worker_client = TestClient(app)
        login(worker_client, "p3a-race@example.com")
        worker_client.headers["X-Tenant-Id"] = tenant_id
        barrier.wait(timeout=5)
        response = worker_client.patch(
            f"/api/v1/companies/{company_id}/revenue/{ret_payload['id']}/linked-sale",
            json={"linked_sale_entry_id": sale_id, "version": ret_payload["version"]},
            headers={"Idempotency-Key": key},
        )
        results.append(response.status_code)

    threads = [
        threading.Thread(target=worker, args=(ret_a.json(), "race-link-a")),
        threading.Thread(target=worker, args=(ret_b.json(), "race-link-b")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert sorted(results) == [200, 422]


def test_void_return_allowed_when_legacy_matches_exceed_gross(
    client, admin, app, fake, tmp_path, migrated_database
) -> None:
    """P3a guard не блокирует void/read при старых данных с превышением лимита."""
    from sqlalchemy import text

    _tenant, company_id = _company(client, admin, app, fake, tmp_path, "p3a-legacy@example.com")
    wallet = _wallet(client, company_id)
    sale = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-10",
            "amount_ex_vat": "833.33",
            "vat_amount": "166.67",
            "amount_inc_vat": "1000.00",
            "entry_type": "sale",
            "external_id": "legacy-sale",
        },
        headers={"Idempotency-Key": "p3a-legacy-sale"},
    )
    assert sale.status_code == 200, sale.text
    sale_row = sale.json()
    cash_a = _cash_in(client, company_id, wallet["id"], "600.00", "p3a-legacy-cash-a")
    cash_b = _cash_in(client, company_id, wallet["id"], "500.00", "p3a-legacy-cash-b")
    first = _revenue_match(
        client, company_id, sale_row["id"], cash_a["id"], "600.00", "p3a-legacy-m1"
    )
    assert first.status_code == 200, first.text
    second = _revenue_match(
        client, company_id, sale_row["id"], cash_b["id"], "500.00", "p3a-legacy-m2"
    )
    assert second.status_code == 422, second.text
    with migrated_database.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO revenue_cash_matches "
                "(id, tenant_id, company_id, revenue_entry_id, cash_transaction_id, "
                "amount, created_by, created_at) "
                "SELECT gen_random_uuid(), tenant_id, company_id, :sale_id, :cash_id, "
                "500.00, created_by, now() FROM revenue_entries WHERE id = :sale_id"
            ),
            {"sale_id": sale_row["id"], "cash_id": cash_b["id"]},
        )
    listed = client.get(f"/api/v1/companies/{company_id}/revenue")
    assert listed.status_code == 200, listed.text
    ret = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-11",
            "amount_ex_vat": "100.00",
            "vat_amount": "20.00",
            "amount_inc_vat": "120.00",
            "entry_type": "return",
            "external_id": "legacy-ret",
        },
        headers={"Idempotency-Key": "p3a-legacy-ret"},
    )
    assert ret.status_code == 200, ret.text
    voided = client.post(
        f"/api/v1/revenue/{ret.json()['id']}/void",
        json={"version": ret.json()["version"]},
    )
    assert voided.status_code == 200, voided.text


def test_guard_counts_only_posted_linked_returns(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _company(client, admin, app, fake, tmp_path, "p3a-void-ret@example.com")
    wallet = _wallet(client, company_id)
    sale = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-10",
            "amount_ex_vat": "6666.67",
            "vat_amount": "1333.33",
            "amount_inc_vat": "8000.00",
            "entry_type": "sale",
            "external_id": "void-sum-sale",
        },
        headers={"Idempotency-Key": "p3a-void-sum-sale"},
    )
    assert sale.status_code == 200, sale.text
    sale_id = sale.json()["id"]
    ret = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-11",
            "amount_ex_vat": "1666.67",
            "vat_amount": "333.33",
            "amount_inc_vat": "2000.00",
            "entry_type": "return",
            "external_id": "void-sum-ret",
            "linked_sale_entry_id": sale_id,
        },
        headers={"Idempotency-Key": "p3a-void-sum-ret"},
    )
    assert ret.status_code == 200, ret.text
    voided = client.post(
        f"/api/v1/revenue/{ret.json()['id']}/void",
        json={"version": ret.json()["version"]},
    )
    assert voided.status_code == 200, voided.text
    cash = _cash_in(client, company_id, wallet["id"], "8000.00", "p3a-void-sum-cash")
    matched = _revenue_match(
        client, company_id, sale_id, cash["id"], "8000.00", "p3a-void-sum-match"
    )
    assert matched.status_code == 200, matched.text
