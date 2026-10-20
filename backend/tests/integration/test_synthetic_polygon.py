"""Сквозной полигон: три вымышленные компании, все контракты импорта FA-R01/R02."""

from __future__ import annotations

from uuid import uuid4

import pytest
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import freeze, login, open_workspace, pay, register_and_verify
from tests.synthetic_polygon.constants import PERIOD_QUERY, polygon_frozen_moment
from tests.synthetic_polygon.expectations import ORACLE, expectation_for, group_rollup
from tests.synthetic_polygon.harness import load_profile
from tests.synthetic_polygon.profiles import ALL_PROFILES, SERVICES


@pytest.fixture(autouse=True)
def _guard_test_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


@pytest.fixture(autouse=True)
def _balances_import_enabled(app):
    app.state.settings.balances_import_enabled = True


def _workspace_three_companies(client, admin, app, fake, tmp_path) -> tuple[str, dict[str, str]]:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, "polygon@example.com", name="Polygon Owner")
    login(client, "polygon@example.com")
    tenant_id = open_workspace(client, "Synthetic Polygon WS")
    pay(client, app, fake, 3, "month")
    company_ids: dict[str, str] = {}
    for profile in ALL_PROFILES:
        created = client.post(
            f"/api/v1/workspaces/{tenant_id}/companies",
            json={
                "name": profile.display_name,
                "kind": "company",
                "timezone": "Europe/Moscow",
            },
        )
        assert created.status_code == 200, created.text
        company_id = created.json()["id"]
        activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
        assert activated.status_code == 200, activated.text
        company_ids[profile.slug] = company_id
    return tenant_id, company_ids


def test_synthetic_polygon_three_companies_dashboard(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    tenant_id, company_ids = _workspace_three_companies(client, admin, app, fake, tmp_path)
    for profile in ALL_PROFILES:
        load_profile(client, company_ids[profile.slug], profile, admin=admin)
        expected = ORACLE[profile.slug]
        board = client.get(
            f"/api/v1/companies/{company_ids[profile.slug]}/dashboard?{PERIOD_QUERY}"
        )
        assert board.status_code == 200, board.text
        values = board.json()["values"]
        assert values["opening_balance"] == expected.opening_balance
        assert values["cash_in"] == expected.cash_in
        assert values["cash_out"] == expected.cash_out
        assert values["net_cash_flow"] == expected.net_cash_flow
        assert values["cash_total"] == expected.cash_total
        assert values["operation_count"] == expected.operation_count
        assert values["revenue"] == expected.revenue_net_ex_vat
        assert values["revenue"] != values["cash_total"]

    rollup = group_rollup()
    group = client.get(f"/api/v1/workspaces/{tenant_id}/group-summary?{PERIOD_QUERY}")
    assert group.status_code == 200, group.text
    metrics = group.json()["metrics"]
    assert metrics["cash_total"] == rollup["cash_total"]
    assert metrics["revenue"] == rollup["revenue"]
    assert metrics["revenue"] != metrics["cash_total"]


def test_synthetic_polygon_subscription_plan_match(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    _tenant, company_ids = _workspace_three_companies(client, admin, app, fake, tmp_path)
    from tests.synthetic_polygon.profiles import SUBSCRIPTION

    load_profile(client, company_ids[SUBSCRIPTION.slug], SUBSCRIPTION, admin=admin)
    events = client.get(
        f"/api/v1/companies/{company_ids[SUBSCRIPTION.slug]}/calendar"
    ).json()["events"]
    plan = next(
        item
        for item in events
        if item["due_date"] == "2026-10-30" and item["amount"] == "2400.00"
    )
    assert plan["remaining"] == "1200.00"


def test_synthetic_polygon_reuses_fa_r01_idempotency(client, admin, app, fake, tmp_path) -> None:
    """Повтор commit cash.csv не дублирует операции (как test_pilot_reconcile / import_api)."""
    freeze(app, polygon_frozen_moment())
    _tenant, company_ids = _workspace_three_companies(client, admin, app, fake, tmp_path)
    company_id = company_ids[SERVICES.slug]
    load_profile(client, company_id, SERVICES, admin=admin)
    before = client.get(f"/api/v1/companies/{company_id}/dashboard?{PERIOD_QUERY}").json()[
        "values"
    ]["operation_count"]
    assert before == expectation_for(SERVICES).operation_count
    sources = client.get(f"/api/v1/companies/{company_id}/sources").json()["sources"]
    cash_source = next(s for s in sources if s["dataset"] == "cash" and s["format"] == "csv")
    from pathlib import Path

    content = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "synthetic_polygon"
        / "services"
        / "cash.csv"
    ).read_bytes()
    repeat = client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": cash_source["id"]},
        files={"upload": ("cash.csv", content, "application/octet-stream")},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert repeat.status_code == 200, repeat.text
    assert client.post(f"/api/v1/imports/{repeat.json()['id']}/commit").status_code == 200
    after = client.get(f"/api/v1/companies/{company_id}/dashboard?{PERIOD_QUERY}").json()[
        "values"
    ]["operation_count"]
    assert after == before
