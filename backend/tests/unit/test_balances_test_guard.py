import os
from dataclasses import dataclass

import pytest
from _pytest.outcomes import Failed
from sqlalchemy.engine import make_url
from tests.integration.balances_test_util import assert_finpilot_test_database


@dataclass
class _EngineStub:
    url: object


def _env_ok(port: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_PG_PORT", str(port))
    base = f"127.0.0.1:{port}/finpilot_test"
    monkeypatch.setenv(
        "DATABASE_URL",
        f"postgresql+psycopg://finpilot_app:secret@{base}",
    )
    monkeypatch.setenv(
        "WORKER_DATABASE_URL",
        f"postgresql+psycopg://finpilot_worker:secret@{base}",
    )
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        f"postgresql+psycopg://127.0.0.1:{port}/finpilot_test",
    )


@pytest.mark.parametrize("port", [5432, 5433])
def test_guard_accepts_local_test_targets(port: int, monkeypatch: pytest.MonkeyPatch) -> None:
    _env_ok(port, monkeypatch)
    engine = _EngineStub(url=make_url(os.environ["DATABASE_URL"]))
    assert_finpilot_test_database(engine)  # type: ignore[arg-type]


def test_guard_rejects_wrong_host(monkeypatch: pytest.MonkeyPatch) -> None:
    _env_ok(5432, monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://u:p@localhost:5432/finpilot_test",
    )
    engine = _EngineStub(url=make_url(os.environ["DATABASE_URL"]))
    with pytest.raises(Failed, match="127.0.0.1"):
        assert_finpilot_test_database(engine)  # type: ignore[arg-type]


def test_guard_rejects_host_substring_not_exact(monkeypatch: pytest.MonkeyPatch) -> None:
    _env_ok(5432, monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://u:p@evil127.0.0.1.evil:5432/finpilot_test",
    )
    engine = _EngineStub(url=make_url(os.environ["DATABASE_URL"]))
    with pytest.raises(Failed, match="127.0.0.1"):
        assert_finpilot_test_database(engine)  # type: ignore[arg-type]


def test_guard_rejects_other_database(monkeypatch: pytest.MonkeyPatch) -> None:
    _env_ok(5432, monkeypatch)
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://u:p@127.0.0.1:5432/finpilot_test_other",
    )
    engine = _EngineStub(url=make_url(os.environ["DATABASE_URL"]))
    with pytest.raises(Failed, match="finpilot_test"):
        assert_finpilot_test_database(engine)  # type: ignore[arg-type]


def test_guard_rejects_disallowed_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_PG_PORT", "5434")
    _env_ok(5434, monkeypatch)
    engine = _EngineStub(url=make_url(os.environ["DATABASE_URL"]))
    with pytest.raises(Failed, match="5432 или 5433"):
        assert_finpilot_test_database(engine)  # type: ignore[arg-type]


def test_guard_rejects_test_pg_port_mismatch_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    _env_ok(5432, monkeypatch)
    engine = _EngineStub(
        url=make_url("postgresql+psycopg://u:p@127.0.0.1:5433/finpilot_test")
    )
    with pytest.raises(Failed, match="engine.url"):
        assert_finpilot_test_database(engine)  # type: ignore[arg-type]


def test_guard_rejects_migration_worker_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _env_ok(5432, monkeypatch)
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+psycopg://127.0.0.1:5433/finpilot_test",
    )
    engine = _EngineStub(url=make_url(os.environ["DATABASE_URL"]))
    with pytest.raises(Failed, match="MIGRATION_DATABASE_URL"):
        assert_finpilot_test_database(engine)  # type: ignore[arg-type]


def test_guard_rejects_missing_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _env_ok(5432, monkeypatch)
    monkeypatch.delenv("DATABASE_URL")
    engine = _EngineStub(url=make_url("postgresql+psycopg://u:p@127.0.0.1:5432/finpilot_test"))
    with pytest.raises(Failed, match="DATABASE_URL обязателен"):
        assert_finpilot_test_database(engine)  # type: ignore[arg-type]


def test_guard_rejects_malformed_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _env_ok(5432, monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "not-a-url")
    engine = _EngineStub(url=make_url("postgresql+psycopg://u:p@127.0.0.1:5432/finpilot_test"))
    with pytest.raises(Failed, match="некорректный URL"):
        assert_finpilot_test_database(engine)  # type: ignore[arg-type]
