"""FA-R06.1-P1: ОДДС полигона vs ручной ORACLE.

Известные дефекты as-is (app/ не менялся):
— cashflow_payload не возвращает completeness (FA-R06.1 §7, P3);
— полнота cash не учитывает coverage_through источника cash;
— при отсутствии cash-источника отчёт всё равно отдаёт суммы (не unavailable).
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import freeze, login, open_workspace, pay, register_and_verify
from tests.synthetic_polygon.cashflow_harness import load_cashflow_sections_profile
from tests.synthetic_polygon.cashflow_oracle import (
    OCTOBER_POLYGON_CASHFLOW,
    design_completeness,
    section_amounts,
)
from tests.synthetic_polygon.constants import PERIOD_QUERY, polygon_frozen_moment
from tests.synthetic_polygon.harness import load_profile
from tests.synthetic_polygon.profiles import ALL_PROFILES, CASHFLOW_SECTIONS


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
    tenant_id = open_workspace(client, "Cashflow P1")
    pay(client, app, fake, 1, "month")
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Cashflow Co", "kind": "company", "timezone": "Europe/Moscow"},
    )
    assert created.status_code == 200, created.text
    company_id = created.json()["id"]
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return company_id


def _cashflow(client, company_id: str, period_query: str = PERIOD_QUERY) -> dict:
    response = client.get(f"/api/v1/companies/{company_id}/cashflow?{period_query}")
    assert response.status_code == 200, response.text
    return response.json()


def _assert_matches_oracle(body: dict, slug: str) -> None:
    oracle = OCTOBER_POLYGON_CASHFLOW[slug]
    amounts = section_amounts(body)
    for section in oracle.sections:
        assert amounts[section.code] == (section.cash_in, section.cash_out)
    assert body["net_external"] == oracle.net_external
    assert body["external_count"] == oracle.external_count
    flags = body["quality_flags"]
    if oracle.expect_unclassified_flag:
        assert "unclassified_operations" in flags
    else:
        assert "unclassified_operations" not in flags
    assert body.get("completeness") is None
    assert oracle.design_completeness == design_completeness(
        has_cash_source=True,
        coverage_through=date.fromisoformat("2026-10-31"),
        date_to=date.fromisoformat("2026-10-31"),
        has_unmapped=oracle.expect_unclassified_flag,
        external_count=oracle.external_count,
    )


@pytest.mark.parametrize("profile", ALL_PROFILES)
def test_polygon_cashflow_matches_october_oracle(
    client, admin, app, fake, tmp_path, profile
) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, f"p1-{profile.slug}@example.com")
    load_profile(client, company_id, profile, admin=admin)
    body = _cashflow(client, company_id)
    _assert_matches_oracle(body, profile.slug)


def test_cashflow_sections_profile_oracle(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(
        client, admin, app, fake, tmp_path, "p1-cashflow-sections@example.com"
    )
    load_cashflow_sections_profile(client, company_id)
    body = _cashflow(client, company_id)
    _assert_matches_oracle(body, CASHFLOW_SECTIONS.slug)


def test_empty_period_with_full_coverage_returns_zeros(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "p1-empty-period@example.com")
    load_profile(client, company_id, ALL_PROFILES[0], admin=admin)
    sources = client.get(f"/api/v1/companies/{company_id}/sources")
    assert sources.status_code == 200, sources.text
    rev_source = next(
        item for item in sources.json()["sources"] if item.get("dataset") == "revenue"
    )
    extended = client.post(
        f"/api/v1/companies/{company_id}/sources/{rev_source['id']}/coverage",
        json={"coverage_through": "2026-11-30"},
    )
    assert extended.status_code == 200, extended.text
    november = "date_from=2026-11-01&date_to=2026-11-30"
    body = _cashflow(client, company_id, november)
    assert body["net_external"] == "0.00"
    assert body["external_count"] == 0
    for item in body["sections"]:
        assert item["in"] == "0.00"
        assert item["out"] == "0.00"
    assert design_completeness(
        has_cash_source=True,
        coverage_through=date.fromisoformat("2026-11-30"),
        date_to=date.fromisoformat("2026-11-30"),
        has_unmapped=False,
        external_count=0,
    ) == "full"
    assert body.get("completeness") is None


def test_partial_cash_coverage_design_preliminary(client, admin, app, fake, tmp_path) -> None:
    """coverage_through < date_to → preliminary; POST /coverage только для revenue."""
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "p1-partial-cov@example.com")
    load_cashflow_sections_profile(client, company_id)
    body = _cashflow(client, company_id)
    assert design_completeness(
        has_cash_source=True,
        coverage_through=date.fromisoformat("2026-10-15"),
        date_to=date.fromisoformat("2026-10-31"),
        has_unmapped=True,
        external_count=body["external_count"],
    ) == "preliminary"
    assert body.get("completeness") is None
    assert body["net_external"] == OCTOBER_POLYGON_CASHFLOW["cashflow_sections"].net_external
    assert "unclassified_operations" in body["quality_flags"]


def test_no_cash_source_design_unavailable(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "p1-no-source@example.com")
    wallet = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Main", "type": "bank", "code": "main"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert wallet.status_code == 200, wallet.text
    wallet_id = wallet.json()["id"]
    opened = client.post(
        f"/api/v1/wallets/{wallet_id}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+00:00", "amount": "1000.00"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert opened.status_code == 200, opened.text
    tx = client.post(
        f"/api/v1/companies/{company_id}/transactions",
        json={
            "wallet_id": wallet_id,
            "direction": "in",
            "amount": "500.00",
            "business_date": "2026-10-05",
            "description": "ручная",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert tx.status_code == 200, tx.text
    body = _cashflow(client, company_id)
    assert design_completeness(
        has_cash_source=False,
        coverage_through=None,
        date_to=date.fromisoformat("2026-10-31"),
        has_unmapped=True,
        external_count=body["external_count"],
    ) == "unavailable"
    assert body.get("completeness") is None
    assert body["net_external"] == "500.00"
    assert body["external_count"] == 1
