"""Регрессия seed/bootstrap E2E (только finpilot_test)."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from tests.e2e.constants import E2E_COMPANY_A, E2E_COMPANY_B, E2E_OWNER_EMAIL
from tests.e2e.database import ensure_finpilot_test_database
from tests.e2e.env import (
    apply_e2e_env,
    validate_e2e_target_config,
    verify_live_finpilot_test,
)
from tests.e2e.seed import run_seed

REPO_ROOT = Path(__file__).resolve().parents[2].parent
META = REPO_ROOT / "frontend" / "e2e" / "fixtures" / "seed-meta.json"


def test_validate_rejects_bad_port() -> None:
    saved = os.environ.get("TEST_PG_PORT", "5432")
    os.environ["TEST_PG_PORT"] = "9999"
    apply_e2e_env()
    with pytest.raises(RuntimeError, match="5432 или 5433"):
        validate_e2e_target_config("9999")
    os.environ["TEST_PG_PORT"] = saved
    apply_e2e_env()


def test_validate_rejects_wrong_database_in_url() -> None:
    apply_e2e_env()
    saved = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = saved.replace("finpilot_test", "other_db")
    with pytest.raises(RuntimeError, match="finpilot_test"):
        validate_e2e_target_config(os.environ.get("TEST_PG_PORT", "5432"))
    os.environ["DATABASE_URL"] = saved


def test_ensure_creates_only_finpilot_test_database() -> None:
    port = apply_e2e_env()
    admin = MagicMock()
    select_result = MagicMock()
    select_result.fetchone.return_value = None
    admin.execute.return_value = select_result

    with patch("tests.e2e.database.admin_connect", return_value=admin):
        ensure_finpilot_test_database(port)

    statements = [call[0][0] for call in admin.execute.call_args_list]
    assert any("CREATE DATABASE" in sql and "finpilot_test" in sql for sql in statements)


def test_seed_creates_two_active_companies() -> None:
    meta = run_seed()
    assert meta["companyAId"]
    assert meta["companyBId"]
    assert META.is_file()
    loaded = json.loads(META.read_text(encoding="utf-8"))
    assert loaded["ownerEmail"] == E2E_OWNER_EMAIL

    port = apply_e2e_env()
    validate_e2e_target_config(port)
    verify_live_finpilot_test(port)

    url = f"postgresql+psycopg://127.0.0.1:{port}/finpilot_test"
    engine = create_engine(url)
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM companies WHERE name IN (:a, :b)"),
            {"a": E2E_COMPANY_A, "b": E2E_COMPANY_B},
        ).scalar_one()
        user = conn.execute(
            text("SELECT email_verified_at IS NOT NULL FROM users WHERE normalized_email = :e"),
            {"e": E2E_OWNER_EMAIL.lower()},
        ).scalar_one()
    engine.dispose()
    assert count == 2
    assert user is True


def test_seed_reruns_on_existing_database() -> None:
    run_seed()
    second = run_seed()
    assert second["companyAId"]
    assert second["companyBId"]
    port = apply_e2e_env()
    url = f"postgresql+psycopg://127.0.0.1:{port}/finpilot_test"
    engine = create_engine(url)
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM companies WHERE name IN (:a, :b)"),
            {"a": E2E_COMPANY_A, "b": E2E_COMPANY_B},
        ).scalar_one()
    engine.dispose()
    assert count == 2
