"""План полигона: external_id, дубликаты amount/due, прогноз vs деньги."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import freeze
from tests.integration.test_import_api import _commit, _upload
from tests.integration.test_synthetic_polygon import _workspace_three_companies
from tests.synthetic_polygon.constants import PERIOD_QUERY, polygon_frozen_moment
from tests.synthetic_polygon.expectations import ORACLE, SERVICES_PLAN_MOVE
from tests.synthetic_polygon.harness import (
    ensure_wallet,
    load_profile,
    plan_event_id,
    plan_namespace,
)
from tests.synthetic_polygon.profiles import SERVICES

PLAN_HEADER = (
    "external_id,direction,amount,currency,due_date,expected_date,"
    "category_code,counterparty_inn,confidence,priority,wallet_code\n"
)


def _forecast(client, company_id: str, as_of: str) -> dict:
    response = client.get(
        f"/api/v1/companies/{company_id}/forecast?as_of={as_of}&scenario=base"
    )
    assert response.status_code == 200, response.text
    return response.json()


def _contribution_date(payload: dict, event_id: str) -> str:
    for item in payload["contributions"]:
        if item["source_id"] == event_id:
            return item["date"]
    raise AssertionError(f"contribution for {event_id} not found")


@pytest.fixture(autouse=True)
def _guard_test_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


@pytest.fixture(autouse=True)
def _balances_import_enabled(app):
    app.state.settings.balances_import_enabled = True


def test_plan_event_id_rejects_duplicate_external_id(
    client, admin, app, fake, tmp_path
) -> None:
    freeze(app, polygon_frozen_moment())
    _tenant, company_ids = _workspace_three_companies(client, admin, app, fake, tmp_path)
    company_id = company_ids[SERVICES.slug]
    load_profile(client, company_id, SERVICES, admin=admin)
    ns = plan_namespace(SERVICES)
    plan_event_id(admin, company_id, "svc-p1", plan_namespace=ns)
    with pytest.raises(LookupError, match="найдено 0"):
        plan_event_id(admin, company_id, "missing-plan", plan_namespace=ns)


def test_plan_same_amount_due_resolved_by_external_id_not_first_row(
    client, admin, app, fake, tmp_path
) -> None:
    freeze(app, polygon_frozen_moment())
    _tenant, company_ids = _workspace_three_companies(client, admin, app, fake, tmp_path)
    company_id = company_ids[SERVICES.slug]
    ensure_wallet(client, company_id)
    source = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "dup-plan",
            "type": "file",
            "namespace": "dup-plan-test",
            "format": "csv",
            "dataset": "plan",
        },
    )
    assert source.status_code == 200, source.text
    body = (
        PLAN_HEADER
        + "dup-a,out,100.00,RUB,2026-10-15,2026-10-15,operating,,expected,normal,main\n"
        + "dup-b,out,100.00,RUB,2026-10-15,2026-10-15,operating,,expected,normal,main\n"
    ).encode()
    uploaded = _upload(
        client, company_id, source.json()["id"], body, "dup.csv", uuid4().hex
    )
    assert uploaded.status_code == 200, uploaded.text
    assert _commit(client, uploaded.json()["id"]).status_code == 200
    dup_ns = "dup-plan-test"
    id_a = plan_event_id(admin, company_id, "dup-a", plan_namespace=dup_ns)
    id_b = plan_event_id(admin, company_id, "dup-b", plan_namespace=dup_ns)
    assert id_a != id_b


def test_plan_move_changes_forecast_not_cash(client, admin, app, fake, tmp_path) -> None:
    oracle = SERVICES_PLAN_MOVE
    freeze(app, polygon_frozen_moment())
    _tenant, company_ids = _workspace_three_companies(client, admin, app, fake, tmp_path)
    company_id = company_ids[SERVICES.slug]
    load_profile(client, company_id, SERVICES, admin=admin)
    event_id = plan_event_id(
        admin, company_id, oracle.plan_external_id, plan_namespace=plan_namespace(SERVICES)
    )
    cash_before = client.get(f"/api/v1/companies/{company_id}/dashboard?{PERIOD_QUERY}").json()[
        "values"
    ]["cash_total"]
    assert cash_before == oracle.cash_total_unchanged
    before = _forecast(client, company_id, oracle.as_of)
    assert _contribution_date(before, event_id) == oracle.forecast_contribution_date_before
    version = client.get(f"/api/v1/companies/{company_id}/calendar").json()["events"]
    row = next(item for item in version if item["id"] == event_id)
    moved = client.patch(
        f"/api/v1/planned-cash/{event_id}",
        json={"version": row["version"], "expected_date": oracle.moved_expected},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["due_date"] == oracle.due_date
    assert moved.json()["expected_date"] == oracle.moved_expected
    after = _forecast(client, company_id, oracle.as_of)
    assert _contribution_date(after, event_id) == oracle.forecast_contribution_date_after
    calendar_after = client.get(f"/api/v1/companies/{company_id}/calendar").json()["events"]
    cal_row = next(item for item in calendar_after if item["id"] == event_id)
    assert cal_row["expected_date"] == oracle.moved_expected
    cash_after = client.get(f"/api/v1/companies/{company_id}/dashboard?{PERIOD_QUERY}").json()[
        "values"
    ]["cash_total"]
    assert cash_after == oracle.cash_total_unchanged
    with admin.connect() as connection:
        tx_count = connection.execute(
            text("SELECT count(*) FROM cash_transactions WHERE company_id = :cid"),
            {"cid": company_id},
        ).scalar_one()
    assert int(tx_count) == ORACLE["services"].operation_count
