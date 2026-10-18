"""Регрессия seed/bootstrap E2E (только finpilot_test)."""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from tests.e2e.constants import E2E_COMPANY_A, E2E_COMPANY_B, E2E_OWNER_EMAIL
from tests.e2e.env import apply_e2e_env, assert_finpilot_test_only
from tests.e2e.seed import run_seed

REPO_ROOT = Path(__file__).resolve().parents[2].parent
META = REPO_ROOT / "frontend" / "e2e" / "fixtures" / "seed-meta.json"


@pytest.fixture(scope="module")
def e2e_port():
    port = apply_e2e_env()
    assert_finpilot_test_only(port)
    return port


def test_seed_creates_two_active_companies(e2e_port: str) -> None:
    meta = run_seed()
    assert meta["companyAId"]
    assert meta["companyBId"]
    assert META.is_file()
    loaded = json.loads(META.read_text(encoding="utf-8"))
    assert loaded["ownerEmail"] == E2E_OWNER_EMAIL

    url = f"postgresql+psycopg://127.0.0.1:{e2e_port}/finpilot_test"
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
