"""Seed finpilot_test для E2E полигона (3 компании, импорты, freeze-совместимый)."""

from __future__ import annotations

import json
from pathlib import Path

from app.clock import FixedClock
from app.integrations.payments import FakeYooKassa
from app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from tests.e2e.database import (
    ensure_finpilot_test_database,
    run_migrations_and_roles,
    truncate_all,
)
from tests.e2e.env import (
    BACKEND,
    apply_e2e_env,
    validate_e2e_target_config,
    verify_live_finpilot_test,
)
from tests.e2e.settings import E2ESettings
from tests.integration.conftest import login, open_workspace, pay, register_and_verify
from tests.synthetic_polygon.constants import polygon_frozen_moment
from tests.synthetic_polygon.harness import load_profile
from tests.synthetic_polygon.profiles import ALL_PROFILES

REPO_ROOT = Path(__file__).resolve().parents[2].parent
META_PATH = REPO_ROOT / "frontend" / "e2e" / "fixtures" / "polygon-meta.json"

POLYGON_OWNER = "polygon-e2e@example.com"
POLYGON_WORKSPACE = "Polygon E2E Workspace"


def prepare_polygon_environment() -> str:
    port = apply_e2e_env()
    validate_e2e_target_config(port)
    ensure_finpilot_test_database(port)
    verify_live_finpilot_test(port)
    run_migrations_and_roles(port)
    truncate_all(port)
    return port


def run_seed() -> dict:
    port = prepare_polygon_environment()
    settings = E2ESettings()
    app = create_app(settings)
    app.state.clock = FixedClock(polygon_frozen_moment())
    import_dir = BACKEND / "var" / "polygon-e2e-imports"
    import_dir.mkdir(parents=True, exist_ok=True)
    app.state.settings.import_storage_dir = str(import_dir)
    Path(app.state.settings.import_storage_dir).mkdir(parents=True, exist_ok=True)
    fake = FakeYooKassa(shop_id="shop-test")
    app.state.payment_provider_factory = lambda: fake

    admin_url = f"postgresql+psycopg://127.0.0.1:{port}/finpilot_test"
    engine = create_engine(admin_url)

    with TestClient(app) as client:
        register_and_verify(client, engine, POLYGON_OWNER, name="Polygon Owner")
        login(client, POLYGON_OWNER)
        tenant_id = open_workspace(client, POLYGON_WORKSPACE)
        pay(client, app, fake, len(ALL_PROFILES), "month")
        company_meta: dict[str, dict] = {}
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
            load_profile(client, company_id, profile, admin=engine)
            company_meta[profile.slug] = {
                "id": company_id,
                "name": profile.display_name,
            }

    app.state.engine.dispose()
    app.state.worker_engine.dispose()
    engine.dispose()

    meta = {
        "ownerEmail": POLYGON_OWNER,
        "workspaceName": POLYGON_WORKSPACE,
        "tenantId": tenant_id,
        "frozenIso": polygon_frozen_moment().isoformat(),
        "companies": company_meta,
    }
    META_PATH.parent.mkdir(parents=True, exist_ok=True)
    META_PATH.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


if __name__ == "__main__":
    print(json.dumps(run_seed(), ensure_ascii=False, indent=2))
