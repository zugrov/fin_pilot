import os

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine, make_url

_ALLOWED_PORTS = frozenset({5432, 5433})
_REQUIRED_HOST = "127.0.0.1"
_REQUIRED_DATABASE = "finpilot_test"
_ENV_URL_KEYS = ("DATABASE_URL", "WORKER_DATABASE_URL", "MIGRATION_DATABASE_URL")


def _normalized_target(raw: str | object) -> tuple[str, int, str]:
    if isinstance(raw, str):
        if not raw.strip():
            raise ValueError("пустой URL")
        try:
            parsed = make_url(raw)
        except Exception as exc:
            raise ValueError("некорректный URL") from exc
    else:
        parsed = raw
    host = parsed.host
    if host is None or host != _REQUIRED_HOST:
        raise ValueError("host должен быть 127.0.0.1")
    port = parsed.port if parsed.port is not None else 5432
    if port not in _ALLOWED_PORTS:
        raise ValueError("port допустим только 5432 или 5433")
    database = parsed.database
    if database != _REQUIRED_DATABASE:
        raise ValueError("database должна быть finpilot_test")
    return host, port, database


def assert_finpilot_test_database(engine: Engine) -> None:
    port_raw = os.environ.get("TEST_PG_PORT", "5432")
    try:
        expected_port = int(port_raw)
    except ValueError:
        pytest.fail("TEST_PG_PORT должен быть числом")
    if expected_port not in _ALLOWED_PORTS:
        pytest.fail("TEST_PG_PORT допустим только 5432 или 5433")

    expected = (_REQUIRED_HOST, expected_port, _REQUIRED_DATABASE)
    try:
        engine_target = _normalized_target(engine.url)
    except ValueError as exc:
        pytest.fail(f"engine: {exc}")
    if engine_target != expected:
        pytest.fail("engine.url не совпадает с целью тестовой БД")

    for key in _ENV_URL_KEYS:
        raw = os.environ.get(key)
        if raw is None or not str(raw).strip():
            pytest.fail(f"{key} обязателен")
        try:
            env_target = _normalized_target(raw)
        except ValueError as exc:
            pytest.fail(f"{key}: {exc}")
        if env_target != expected:
            pytest.fail(f"{key} не совпадает с TEST_PG_PORT и finpilot_test")

    if len({_normalized_target(os.environ[k]) for k in _ENV_URL_KEYS}) != 1:
        pytest.fail("DATABASE_URL, WORKER_DATABASE_URL и MIGRATION_DATABASE_URL расходятся")


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
