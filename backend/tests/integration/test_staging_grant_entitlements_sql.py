"""Интеграция: scripts/staging_grant_entitlements.sql на мигрированной БД."""

from __future__ import annotations

import importlib.util
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from tests.integration.conftest import freeze, login, open_workspace, register_and_verify

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGING_SCRIPT = REPO_ROOT / "scripts" / "staging_acceptance.py"

def _load_staging_module():
    spec = importlib.util.spec_from_file_location("staging_acceptance_it", STAGING_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _exec_sql_script(admin, script: str) -> None:
    with admin.connect() as connection:
        connection.exec_driver_sql(script)
        connection.commit()


def _create_companies(client, tenant_id: str, count: int = 4) -> list[str]:
    ids: list[str] = []
    for index in range(count):
        created = client.post(
            f"/api/v1/workspaces/{tenant_id}/companies",
            json={
                "name": f"Staging grant {index + 1}",
                "kind": "company",
                "timezone": "Europe/Moscow",
            },
        )
        assert created.status_code == 200, created.text
        ids.append(created.json()["id"])
    return ids


def _subscription_row(admin, tenant_id: str) -> dict:
    with admin.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT status, company_limit, paid_through::text
                FROM subscriptions
                WHERE tenant_id = :tenant_id
                """
            ),
            {"tenant_id": tenant_id},
        ).mappings().one()
    return dict(row)


def _company_statuses(admin, tenant_id: str) -> list[str]:
    with admin.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT status FROM companies
                WHERE tenant_id = :tenant_id
                ORDER BY created_at, id
                """
            ),
            {"tenant_id": tenant_id},
        ).scalars().all()
    return list(rows)


def test_staging_grant_sql_dashboard_activate_rollback(client, admin, app) -> None:
    staging = _load_staging_module()
    freeze(app, datetime(2026, 10, 14, 12, tzinfo=UTC))
    email = f"staging-sql-{uuid.uuid4().hex[:8]}@example.com"
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client)

    company_ids = _create_companies(client, tenant_id, 4)
    before_sub = _subscription_row(admin, tenant_id)
    before_statuses = _company_statuses(admin, tenant_id)

    period_id = str(uuid.uuid4())
    grant_sql, rollback_sql = staging.render_staging_entitlement_sql(
        tenant_id=tenant_id,
        company_ids=company_ids,
        period_id=period_id,
        company_limit=4,
    )

    probe = company_ids[0]
    denied = client.get(
        f"/api/v1/companies/{probe}/dashboard",
        params={"date_from": "2026-10-01", "date_to": "2026-10-31"},
    )
    assert denied.status_code == 402

    _exec_sql_script(admin, grant_sql)

    dashboard = client.get(
        f"/api/v1/companies/{probe}/dashboard",
        params={"date_from": "2026-10-01", "date_to": "2026-10-31"},
    )
    assert dashboard.status_code == 200, dashboard.text

    activated = client.post(f"/api/v1/billing/companies/{probe}/activate")
    assert activated.status_code == 200, activated.text

    _exec_sql_script(admin, rollback_sql)

    after_sub = _subscription_row(admin, tenant_id)
    after_statuses = _company_statuses(admin, tenant_id)
    assert after_sub["status"] == before_sub["status"]
    assert after_sub["company_limit"] == before_sub["company_limit"]
    assert after_sub["paid_through"] == before_sub["paid_through"]
    assert after_statuses == before_statuses

    denied_again = client.get(
        f"/api/v1/companies/{probe}/dashboard",
        params={"date_from": "2026-10-01", "date_to": "2026-10-31"},
    )
    assert denied_again.status_code == 402
