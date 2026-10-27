"""FA-R06.1-P3b: API receivable-aging и ORACLE P2."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from tests.integration.conftest import (
    latest_link,
    login,
    open_workspace,
    pay,
    register_and_verify,
    token_from_link,
)
from tests.integration.test_revenue_api import _ready
from tests.synthetic_polygon.receivable_harness import (
    apply_receivable_demo_matches,
    load_receivable_demo_profile,
)
from tests.synthetic_polygon.receivable_oracle import (
    AS_OF,
    UNALLOCATED_CASH_RECEIPTS,
    total_balance,
    totals_by_bucket,
    totals_by_counterparty,
)

AS_OF_QUERY = AS_OF.isoformat()


@pytest.fixture(autouse=True)
def _balances_import_enabled(app):
    app.state.settings.balances_import_enabled = True


def _company(client, admin, app, fake, tmp_path, email: str) -> str:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "AR P3b")
    pay(client, app, fake, 1, "month")
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "AR Co", "kind": "company", "timezone": "Europe/Moscow"},
    )
    assert created.status_code == 200, created.text
    company_id = created.json()["id"]
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return company_id


def _report(client, company_id: str, *, as_of: str = AS_OF_QUERY) -> dict:
    resp = client.get(
        f"/api/v1/companies/{company_id}/reports/receivable-aging",
        params={"as_of": as_of},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_receivable_aging_matches_oracle_p2(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "ar-oracle@example.com")
    load_receivable_demo_profile(client, company_id)
    apply_receivable_demo_matches(client, company_id)
    body = _report(client, company_id)
    assert Decimal(body["total_balance"]) == total_balance()
    buckets = body["totals_by_bucket"]
    expected = totals_by_bucket()
    for key in ("0-30", "31-60", "61-90", ">90"):
        assert Decimal(buckets[key]) == expected[key]
    by_inn = {item["inn"]: Decimal(item["balance"]) for item in body["totals_by_counterparty"]}
    subs = totals_by_counterparty()
    assert by_inn["7700000901"] == subs["7700000901"]
    assert by_inn["7700000902"] == subs["7700000902"]
    assert by_inn[None] == subs[None]
    unalloc = sum(Decimal(item["amount"]) for item in body["unallocated_receipts"])
    assert unalloc == UNALLOCATED_CASH_RECEIPTS[0]["amount"]


def test_receivable_aging_orphan_return_and_void_linked_sale(
    client, admin, app, fake, tmp_path
) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "ar-orphan@example.com")
    load_receivable_demo_profile(client, company_id)
    body = _report(client, company_id)
    orphans = [row for row in body["rows"] if row["orphan_return"]]
    assert not orphans
    sale = next(row for row in body["rows"] if row["document"]["external_id"] == "rd-r-c-sale")
    assert Decimal(sale["balance"]) == Decimal("6000.00")
    listed = client.get(f"/api/v1/companies/{company_id}/revenue")
    entries = listed.json()["entries"]
    sale_row = next(item for item in entries if item["external_id"] == "rd-r-c-sale")
    voided = client.post(
        f"/api/v1/revenue/{sale_row['id']}/void",
        json={"version": sale_row["version"]},
    )
    assert voided.status_code == 200, voided.text
    after = _report(client, company_id)
    orphan = next(row for row in after["rows"] if row["document"]["external_id"] == "rd-r-c-ret")
    assert orphan["orphan_return"] is True
    assert Decimal(orphan["balance"]) == Decimal("-2000.00")


def test_receivable_aging_as_of_before_payment_and_return(
    client, admin, app, fake, tmp_path
) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "ar-asof@example.com")
    load_receivable_demo_profile(client, company_id)
    apply_receivable_demo_matches(client, company_id)
    early = _report(client, company_id, as_of="2026-10-28")
    paid_row = next(row for row in early["rows"] if row["document"]["external_id"] == "rd-r-paid")
    assert Decimal(paid_row["balance"]) == Decimal("10000.00")
    late = _report(client, company_id, as_of="2026-10-29")
    assert not any(row["document"]["external_id"] == "rd-r-paid" for row in late["rows"])
    before_ret = _report(client, company_id, as_of="2026-10-13")
    sale = next(
        row for row in before_ret["rows"] if row["document"]["external_id"] == "rd-r-c-sale"
    )
    assert Decimal(sale["balance"]) == Decimal("8000.00")


def test_receivable_aging_rows_truncated(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "ar-trunc@example.com")
    app.state.settings.receivable_aging_max_rows = 3
    load_receivable_demo_profile(client, company_id)
    body = _report(client, company_id)
    assert body["rows_truncated"] is True
    assert len(body["rows"]) == 3


def test_receivable_aging_forbidden_and_not_found(client, admin, app, fake, tmp_path) -> None:
    tenant, company_id = _ready(client, admin, app, fake, tmp_path, "ar-guard@example.com")
    foreign = TestClient(app)
    _ready(foreign, admin, app, fake, tmp_path, "ar-other@example.com")
    assert (
        foreign.get(
            f"/api/v1/companies/{company_id}/reports/receivable-aging",
            params={"as_of": AS_OF_QUERY},
        ).status_code
        == 404
    )
    invited = client.post(
        f"/api/v1/workspaces/{tenant}/invitations",
        json={"email": "ar-op@example.com", "role": "operator"},
    )
    assert invited.status_code == 200, invited.text
    token = token_from_link(latest_link(admin))
    guest = TestClient(app)
    register_and_verify(guest, admin, "ar-op@example.com", name="Оператор")
    login(guest, "ar-op@example.com")
    guest.post("/api/v1/auth/invitations/accept", json={"token": token})
    guest.headers["X-Tenant-Id"] = tenant
    logged = guest.get("/api/v1/auth/me").json()
    granted = client.post(
        f"/api/v1/workspaces/{tenant}/company-access",
        json={"user_id": logged["user"]["id"], "company_id": company_id},
    )
    assert granted.status_code == 200, granted.text
    denied = guest.get(
        f"/api/v1/companies/{company_id}/reports/receivable-aging",
        params={"as_of": AS_OF_QUERY},
    )
    assert denied.status_code == 403, denied.text


def test_receivable_aging_invalid_as_of(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "ar-bad-date@example.com")
    bad = client.get(
        f"/api/v1/companies/{company_id}/reports/receivable-aging",
        params={"as_of": "not-a-date"},
    )
    assert bad.status_code == 422, bad.text


def test_receivable_aging_completeness_unavailable(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "ar-unavail@example.com")
    body = _report(client, company_id)
    assert body["completeness"] == "unavailable"
    assert "missing_revenue_source" in body["quality_flags"]
