"""FA-R06.1-P2: профиль receivable_demo и ORACLE дебиторки."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import login, open_workspace, pay, register_and_verify
from tests.integration.test_sales_plan_matching import _revenue_match
from tests.synthetic_polygon.receivable_harness import (
    _cash_id_by_external_id,
    apply_receivable_demo_matches,
    load_receivable_demo_profile,
)
from tests.synthetic_polygon.receivable_oracle import (
    AS_OF,
    RECEIVABLE_DEMO_ROWS,
    UNALLOCATED_CASH_RECEIPTS,
    aging_report_rows,
    matches_plus_return_exceed_gross,
    rd_c_logical_line,
    total_balance,
    totals_by_bucket,
    totals_by_counterparty,
)


@pytest.fixture(autouse=True)
def _guard_test_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


@pytest.fixture(autouse=True)
def _balances_import_enabled(app):
    app.state.settings.balances_import_enabled = True


def _company(client, admin, app, fake, tmp_path, email: str) -> str:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Receivable P2")
    pay(client, app, fake, 1, "month")
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Receivable Demo Co", "kind": "company", "timezone": "Europe/Moscow"},
    )
    assert created.status_code == 200, created.text
    company_id = created.json()["id"]
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return company_id


def test_oracle_bucket_boundary_ages() -> None:
    by_id = {row.doc_id: row for row in RECEIVABLE_DEMO_ROWS}
    assert by_id["rd-r-b30"].age_days == 30 and by_id["rd-r-b30"].bucket == "0-30"
    assert by_id["rd-r-b31"].age_days == 31 and by_id["rd-r-b31"].bucket == "31-60"
    assert by_id["rd-r-b60"].age_days == 60 and by_id["rd-r-b60"].bucket == "31-60"
    assert by_id["rd-r-b61"].age_days == 61 and by_id["rd-r-b61"].bucket == "61-90"
    assert by_id["rd-r-b90"].age_days == 90 and by_id["rd-r-b90"].bucket == "61-90"
    assert by_id["rd-r-b91"].age_days == 91 and by_id["rd-r-b91"].bucket == ">90"


def test_oracle_total_balance_and_buckets() -> None:
    assert total_balance() == Decimal("47506.00")
    buckets = totals_by_bucket()
    assert buckets["0-30"] == Decimal("32501.00")
    assert buckets["31-60"] == Decimal("5002.00")
    assert buckets["61-90"] == Decimal("5002.00")
    assert buckets[">90"] == Decimal("5001.00")


def test_oracle_counterparty_subtotals_and_unallocated() -> None:
    subs = totals_by_counterparty()
    assert subs[None] == Decimal("1500.00")
    assert subs["7700000901"] == Decimal("25000.00")
    assert subs["7700000902"] == Decimal("21006.00")
    assert UNALLOCATED_CASH_RECEIPTS[0]["amount"] == Decimal("15000.00")
    paid = next(row for row in RECEIVABLE_DEMO_ROWS if row.doc_id == "rd-r-paid")
    assert paid.balance == Decimal("0")
    assert paid not in aging_report_rows()


def test_oracle_each_row_balance_postrochno() -> None:
    expected = {
        "rd-r-a": Decimal("12000.00"),
        "rd-r-b": Decimal("6000.00"),
        "rd-r-c-sale": Decimal("8000.00"),
        "rd-r-c-ret": Decimal("-2000.00"),
        "rd-r-d": Decimal("6000.00"),
        "rd-r-e": Decimal("1500.00"),
        "rd-r-f1": Decimal("5000.00"),
        "rd-r-f2": Decimal("5000.00"),
        "rd-r-f3": Decimal("5000.00"),
        "rd-r-b30": Decimal("1.00"),
        "rd-r-b31": Decimal("1.00"),
        "rd-r-b60": Decimal("1.00"),
        "rd-r-b61": Decimal("1.00"),
        "rd-r-b90": Decimal("1.00"),
        "rd-r-b91": Decimal("1.00"),
        "rd-r-over": Decimal("1000.00"),
    }
    for row in RECEIVABLE_DEMO_ROWS:
        if row.doc_id in expected:
            assert row.balance == expected[row.doc_id], row.doc_id


def test_receivable_demo_load_unallocated_matches_oracle(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "rd-p2-load@example.com")
    load_receivable_demo_profile(client, company_id)
    apply_receivable_demo_matches(client, company_id)
    listed = client.get(f"/api/v1/companies/{company_id}/revenue")
    assert listed.status_code == 200, listed.text
    by_ext = {item["external_id"]: item for item in listed.json()["entries"]}
    assert by_ext["rd-r-b"]["matched_amount"] == "4000.00"
    assert by_ext["rd-r-b"]["unallocated_amount"] == "6000.00"
    assert by_ext["rd-r-paid"]["unallocated_amount"] == "0.00"
    assert by_ext["rd-r-d"]["unallocated_amount"] == "6000.00"


def test_oracle_rd_c_matches_plus_return_exceed_gross_single_logical_line() -> None:
    gross, return_amt = rd_c_logical_line()
    assert gross == Decimal("8000.00") and return_amt == Decimal("2000.00")
    matched = Decimal("6501.00")
    assert matches_plus_return_exceed_gross(gross, return_amt, matched)
    assert not matches_plus_return_exceed_gross(gross, return_amt, Decimal("6000.00"))


def test_revenue_match_sum_exceeds_gross_returns_422(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "rd-p2-over@example.com")
    load_receivable_demo_profile(client, company_id)
    listed = client.get(f"/api/v1/companies/{company_id}/revenue")
    over = next(item for item in listed.json()["entries"] if item["external_id"] == "rd-r-over")
    cash1_id = _cash_id_by_external_id(client, company_id, "rd-c-over")
    cash2_id = _cash_id_by_external_id(client, company_id, "rd-c-over2")
    first = _revenue_match(client, company_id, over["id"], cash1_id, "600.00", uuid4().hex)
    assert first.status_code == 200, first.text
    second = _revenue_match(client, company_id, over["id"], cash2_id, "500.00", uuid4().hex)
    assert second.status_code == 422, second.text
    assert second.json()["code"] == "validation_error"


@pytest.mark.skip(reason="P3")
def test_receivable_aging_service_matches_oracle() -> None:
    raise AssertionError("receivable_aging_service — пакет FA-R06.1-P3")
