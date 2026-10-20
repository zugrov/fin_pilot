"""Ограничение полигона: cash_total «на сейчас» vs обороты за период (intraday_approximation)."""

from __future__ import annotations

from datetime import UTC, datetime

from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import freeze
from tests.integration.test_synthetic_polygon import _workspace_three_companies
from tests.synthetic_polygon.constants import PERIOD_QUERY
from tests.synthetic_polygon.harness import load_profile
from tests.synthetic_polygon.profiles import SERVICES


def test_polygon_cash_total_midday_before_same_day_outflow(
    client, admin, app, fake, tmp_path
) -> None:
    """На полдень 20.10 outflow с business_date=20.10 ещё не в остатке, но в оборотах периода."""
    assert_finpilot_test_database(admin)
    app.state.settings.balances_import_enabled = True
    freeze(app, datetime(2026, 10, 20, 9, 0, tzinfo=UTC))
    _tenant, company_ids = _workspace_three_companies(client, admin, app, fake, tmp_path)
    load_profile(client, company_ids[SERVICES.slug], SERVICES, admin=admin)
    values = client.get(
        f"/api/v1/companies/{company_ids[SERVICES.slug]}/dashboard?{PERIOD_QUERY}"
    ).json()["values"]
    assert values["cash_in"] == "20000.00"
    assert values["cash_out"] == "3000.00"
    assert values["net_cash_flow"] == "17000.00"
    assert values["opening_balance"] == "50000.00"
    # Остаток на 20.10 12:00 MSK: out 20.10 ещё не применён к cash_total.
    assert values["cash_total"] == "70000.00"
