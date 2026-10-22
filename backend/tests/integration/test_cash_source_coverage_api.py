"""POST /sources/{id}/coverage для cash (FA-R06.2-A)."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import (
    freeze,
    latest_link,
    login,
    open_workspace,
    pay,
    register_and_verify,
    token_from_link,
)
from tests.synthetic_polygon.constants import COVERAGE_THROUGH, PERIOD_QUERY, polygon_frozen_moment
from tests.synthetic_polygon.harness import load_profile
from tests.synthetic_polygon.profiles import ALL_PROFILES


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
    tenant_id = open_workspace(client, "Coverage API")
    company = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Фирма", "kind": "company", "timezone": "Europe/Moscow"},
    )
    assert company.status_code == 200, company.text
    company_id = company.json()["id"]
    pay(client, app, fake, 1, "month")
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return company_id


def _ready(client, admin, app, fake, tmp_path, email: str) -> tuple[str, str]:
    company_id = _company(client, admin, app, fake, tmp_path, email)
    wallet = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Main", "type": "bank", "code": f"w-{uuid4().hex[:8]}"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert wallet.status_code == 200, wallet.text
    return company_id, wallet.json()["id"]


def _cash_source(client, company_id: str, wallet_id: str, namespace: str = "cash-cov") -> str:
    created = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Cash file",
            "type": "file",
            "namespace": namespace,
            "format": "csv",
            "dataset": "cash",
            "wallet_id": wallet_id,
        },
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _revenue_source(client, company_id: str) -> str:
    created = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Revenue",
            "type": "file",
            "namespace": "rev-cov",
            "format": "csv",
            "dataset": "revenue",
        },
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _post_coverage(client, company_id: str, source_id: str, coverage_through: str):
    return client.post(
        f"/api/v1/companies/{company_id}/sources/{source_id}/coverage",
        json={"coverage_through": coverage_through},
    )


def test_cash_coverage_happy_path_and_cashflow_full(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "cash-cov-ok@example.com")
    load_profile(client, company_id, ALL_PROFILES[0], admin=admin)
    sources = client.get(f"/api/v1/companies/{company_id}/sources").json()["sources"]
    cash_ids = [item["id"] for item in sources if item["dataset"] == "cash"]
    assert cash_ids
    before = client.get(f"/api/v1/companies/{company_id}/cashflow?{PERIOD_QUERY}").json()
    assert before["completeness"] == "preliminary"
    assert "partial_period" in before["quality_flags"]
    for source_id in cash_ids:
        response = _post_coverage(client, company_id, source_id, COVERAGE_THROUGH)
        assert response.status_code == 200, response.text
        assert response.json()["dataset"] == "cash"
    after = client.get(f"/api/v1/companies/{company_id}/cashflow?{PERIOD_QUERY}").json()
    assert after["completeness"] == "full"
    assert "partial_period" not in after["quality_flags"]
    with admin.connect() as connection:
        audit = connection.execute(
            text(
                "SELECT count(*) FROM audit_log WHERE action = 'cash_coverage_set' "
                "AND entity_id = CAST(:id AS uuid)"
            ),
            {"id": cash_ids[0]},
        ).scalar_one()
    assert audit >= 1


def test_revenue_coverage_decrease_allowed(client, admin, app, fake, tmp_path) -> None:
    company_id, _wallet = _ready(
        client, admin, app, fake, tmp_path, "cov-dec-rev@example.com"
    )
    source_id = _revenue_source(client, company_id)
    assert _post_coverage(client, company_id, source_id, "2026-10-31").status_code == 200
    decreased = _post_coverage(client, company_id, source_id, "2026-10-15")
    assert decreased.status_code == 200, decreased.text
    assert decreased.json()["coverage_through"] == "2026-10-15"


def test_cash_coverage_decrease_matches_revenue_rule(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(
        client, admin, app, fake, tmp_path, "cov-dec-cash@example.com"
    )
    source_id = _cash_source(client, company_id, wallet_id)
    assert _post_coverage(client, company_id, source_id, "2026-10-31").status_code == 200
    decreased = _post_coverage(client, company_id, source_id, "2026-10-15")
    assert decreased.status_code == 200, decreased.text
    assert decreased.json()["coverage_through"] == "2026-10-15"


def test_coverage_repeat_same_date_increments_dataset_coverage_version(
    client, admin, app, fake, tmp_path
) -> None:
    company_id, wallet_id = _ready(
        client, admin, app, fake, tmp_path, "cov-repeat@example.com"
    )
    source_id = _cash_source(client, company_id, wallet_id)
    date = "2026-10-20"
    assert _post_coverage(client, company_id, source_id, date).status_code == 200
    again = _post_coverage(client, company_id, source_id, date)
    assert again.status_code == 200, again.text
    with admin.connect() as connection:
        versions = connection.execute(
            text(
                "SELECT version FROM dataset_coverage WHERE connection_id = CAST(:c AS uuid) "
                "AND period_start = CAST(:d AS date) ORDER BY version"
            ),
            {"c": source_id, "d": date},
        ).fetchall()
        reconciled = connection.execute(
            text(
                "SELECT count(*) FROM dataset_coverage WHERE connection_id = CAST(:c AS uuid) "
                "AND state = 'reconciled'"
            ),
            {"c": source_id},
        ).scalar_one()
    assert [row[0] for row in versions] == [1, 2]
    assert reconciled == 0


def test_viewer_cannot_set_coverage(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(
        client, admin, app, fake, tmp_path, "cov-owner@example.com"
    )
    tenant = client.headers["X-Tenant-Id"]
    source_id = _cash_source(client, company_id, wallet_id)
    invited = client.post(
        f"/api/v1/workspaces/{tenant}/invitations",
        json={"email": "cov-viewer@example.com", "role": "viewer"},
    )
    assert invited.status_code == 200, invited.text
    invite_token = token_from_link(latest_link(admin))
    guest = TestClient(app)
    register_and_verify(guest, admin, "cov-viewer@example.com")
    guest_login = login(guest, "cov-viewer@example.com")
    accepted = guest.post(
        "/api/v1/auth/invitations/accept",
        json={"token": invite_token},
    )
    assert accepted.status_code == 200, accepted.text
    guest.headers["X-Tenant-Id"] = tenant
    grant = client.post(
        f"/api/v1/workspaces/{tenant}/company-access",
        json={"user_id": guest_login["user"]["id"], "company_id": company_id},
    )
    assert grant.status_code == 200, grant.text
    denied = _post_coverage(guest, company_id, source_id, COVERAGE_THROUGH)
    assert denied.status_code == 403


def test_unpaid_subscription_blocks_coverage(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(
        client, admin, app, fake, tmp_path, "cov-unpaid@example.com"
    )
    source_id = _cash_source(client, company_id, wallet_id)
    end = client.get("/api/v1/billing/subscription").json()["paid_through"]
    freeze(app, datetime.fromisoformat(end) + timedelta(seconds=1))
    login(client, "cov-unpaid@example.com")
    memberships = client.get("/api/v1/auth/me").json()["memberships"]
    client.headers["X-Tenant-Id"] = memberships[0]["tenant_id"]
    blocked = _post_coverage(client, company_id, source_id, COVERAGE_THROUGH)
    assert blocked.status_code == 402


def test_foreign_company_source_returns_404(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(
        client, admin, app, fake, tmp_path, "cov-a@example.com"
    )
    source_id = _cash_source(client, company_id, wallet_id)
    other = TestClient(app)
    _company(other, admin, app, fake, tmp_path, "cov-b@example.com")
    hidden = _post_coverage(other, company_id, source_id, COVERAGE_THROUGH)
    assert hidden.status_code == 404
