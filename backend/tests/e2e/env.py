"""Test-only окружение для E2E API (без чтения .env)."""

from __future__ import annotations

import os
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def apply_e2e_env() -> str:
    port = os.environ.get("TEST_PG_PORT", "5432")
    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = (
        f"postgresql+psycopg://finpilot_app:finpilot_test_only@127.0.0.1:{port}/finpilot_test"
    )
    os.environ["WORKER_DATABASE_URL"] = (
        f"postgresql+psycopg://finpilot_worker:finpilot_test_only@127.0.0.1:{port}/finpilot_test"
    )
    os.environ["MIGRATION_DATABASE_URL"] = f"postgresql+psycopg://127.0.0.1:{port}/finpilot_test"
    os.environ["SESSION_COOKIE_SECURE"] = "false"
    os.environ["EMAIL_PROVIDER_MODE"] = "mock"
    os.environ["SEND_REAL_EMAIL"] = "false"
    os.environ["SEND_LIVE_PAYMENTS"] = "false"
    os.environ["SEND_EXTERNAL_MESSAGES"] = "false"
    os.environ["BILLING_MODE"] = "test"
    os.environ["RATE_LIMIT_BACKEND"] = "memory"
    os.environ["YOOKASSA_SHOP_ID"] = "shop-test"
    os.environ["PUBLIC_BASE_URL"] = "http://127.0.0.1:5173"
    os.environ["CORS_ORIGINS"] = "http://127.0.0.1:5173"
    os.environ["ANNUAL_BILLING_ENABLED"] = "true"
    os.environ["REFUNDS_ENABLED"] = "false"
    os.environ["BILLING_GUARD_BYPASS"] = "false"
    import_dir = BACKEND / "var" / "e2e-imports"
    import_dir.mkdir(parents=True, exist_ok=True)
    os.environ["IMPORT_STORAGE_DIR"] = str(import_dir)
    return port


def assert_finpilot_test_only(port: str) -> None:
    from sqlalchemy import create_engine, text

    url = f"postgresql+psycopg://127.0.0.1:{port}/finpilot_test"
    engine = create_engine(url)
    with engine.connect() as conn:
        name = conn.execute(text("SELECT current_database()")).scalar_one()
    engine.dispose()
    if name != "finpilot_test":
        raise RuntimeError(f"E2E разрешена только finpilot_test, получено {name}")
