import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine


def assert_finpilot_test_database(engine: Engine) -> None:
    port = os.environ.get("TEST_PG_PORT", "5432")
    if port != "5432":
        pytest.fail("TEST_PG_PORT должен быть 5432")
    url = os.environ.get("DATABASE_URL", "")
    if "127.0.0.1" not in url or "/finpilot_test" not in url:
        pytest.fail("DATABASE_URL должен указывать на 127.0.0.1/finpilot_test")


def opening_counts(admin: Engine, wallet_id: str) -> dict[str, int]:
    with admin.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT status, count(*)::int FROM opening_balances "
                "WHERE wallet_id = :wid GROUP BY status"
            ),
            {"wid": wallet_id},
        ).all()
    return {str(status): count for status, count in rows}


def opening_total(admin: Engine, wallet_id: str) -> int:
    with admin.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM opening_balances WHERE wallet_id = :wid"),
                {"wid": wallet_id},
            ).scalar_one()
        )


def audit_opening_total(admin: Engine, wallet_id: str) -> int:
    with admin.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM audit_log a "
                    "JOIN opening_balances o ON o.id = a.entity_id "
                    "WHERE o.wallet_id = :wid AND a.action = 'opening_balance_set'"
                ),
                {"wid": wallet_id},
            ).scalar_one()
        )


def batch_status(admin: Engine, batch_id: str) -> str:
    with admin.connect() as connection:
        return str(
            connection.execute(
                text("SELECT status FROM import_batches WHERE id = :id"),
                {"id": batch_id},
            ).scalar_one()
        )


def batch_has_completed_response(admin: Engine, batch_id: str) -> bool:
    with admin.connect() as connection:
        payload = connection.execute(
            text(
                "SELECT r.normalized_payload FROM raw_import_rows r "
                "JOIN import_batches b ON b.id = r.batch_id "
                "WHERE b.id = :id ORDER BY r.row_number LIMIT 1"
            ),
            {"id": batch_id},
        ).scalar_one()
    if not isinstance(payload, dict):
        return False
    block = payload.get("_batch_preview") or {}
    completed = block.get("completed_response")
    return isinstance(completed, dict) and bool(completed)
