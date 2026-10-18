"""Синтетический seed для E2E: verified owner, workspace, две оплаченные фирмы."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.clock import FixedClock
from app.integrations.payments import FakeYooKassa
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from tests.e2e.constants import (
    E2E_COMPANY_A,
    E2E_COMPANY_B,
    E2E_FROZEN_ISO,
    E2E_OWNER_EMAIL,
    E2E_WORKSPACE,
)
from tests.e2e.database import ensure_database_and_roles, truncate_all
from tests.e2e.env import apply_e2e_env, assert_finpilot_test_only
from tests.e2e.settings import E2ESettings
from tests.integration.conftest import (
    login,
    open_workspace,
    pay,
    register_and_verify,
)

REPO_ROOT = Path(__file__).resolve().parents[2].parent
META_PATH = REPO_ROOT / "frontend" / "e2e" / "fixtures" / "seed-meta.json"


def _company_id(admin_url: str, name: str) -> str:
    engine = create_engine(admin_url)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT id FROM companies WHERE name = :name ORDER BY created_at LIMIT 1"),
            {"name": name},
        ).scalar_one()
    engine.dispose()
    return str(row)


def run_seed() -> dict:
    port = apply_e2e_env()
    assert_finpilot_test_only(port)
    ensure_database_and_roles(port)
    truncate_all(port)

    settings = E2ESettings()
    app = create_app(settings)
    frozen = datetime.fromisoformat(E2E_FROZEN_ISO)
    if frozen.tzinfo is None:
        frozen = frozen.replace(tzinfo=UTC)
    app.state.clock = FixedClock(frozen)
    fake = FakeYooKassa(shop_id="shop-test")
    app.state.payment_provider_factory = lambda: fake

    admin_url = f"postgresql+psycopg://127.0.0.1:{port}/finpilot_test"
    engine = create_engine(admin_url)

    with TestClient(app) as client:
        register_and_verify(client, engine, E2E_OWNER_EMAIL, name="E2E Owner")
        login(client, E2E_OWNER_EMAIL)
        tenant_id = open_workspace(client, E2E_WORKSPACE)
        company_ids: list[str] = []
        for company_name in (E2E_COMPANY_A, E2E_COMPANY_B):
            created = client.post(
                f"/api/v1/workspaces/{tenant_id}/companies",
                json={
                    "name": company_name,
                    "kind": "company",
                    "timezone": "Europe/Moscow",
                },
            )
            assert created.status_code == 200, created.text
            company_ids.append(created.json()["id"])
        pay(client, app, fake, 2, "month")
        for company_id in company_ids:
            activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
            assert activated.status_code == 200, activated.text

    app.state.engine.dispose()
    app.state.worker_engine.dispose()
    engine.dispose()

    meta = {
        "ownerEmail": E2E_OWNER_EMAIL,
        "workspaceName": E2E_WORKSPACE,
        "companyAName": E2E_COMPANY_A,
        "companyBName": E2E_COMPANY_B,
        "companyAId": _company_id(admin_url, E2E_COMPANY_A),
        "companyBId": _company_id(admin_url, E2E_COMPANY_B),
        "frozenDate": "2026-10-18",
    }
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


if __name__ == "__main__":
    print(json.dumps(run_seed(), ensure_ascii=False, indent=2))
