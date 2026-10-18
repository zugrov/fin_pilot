"""Test-only окружение для E2E API (без чтения .env)."""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlparse

BACKEND = Path(__file__).resolve().parents[2]

E2E_HOST = "127.0.0.1"
E2E_DATABASE = "finpilot_test"
ALLOWED_PG_PORTS = frozenset({"5432", "5433"})

_URL_KEYS = ("DATABASE_URL", "WORKER_DATABASE_URL", "MIGRATION_DATABASE_URL")


def apply_e2e_env() -> str:
    port = os.environ.get("TEST_PG_PORT", "5432")
    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = (
        f"postgresql+psycopg://finpilot_app:finpilot_test_only@{E2E_HOST}:{port}/{E2E_DATABASE}"
    )
    os.environ["WORKER_DATABASE_URL"] = (
        f"postgresql+psycopg://finpilot_worker:finpilot_test_only@{E2E_HOST}:{port}/{E2E_DATABASE}"
    )
    os.environ["MIGRATION_DATABASE_URL"] = (
        f"postgresql+psycopg://{E2E_HOST}:{port}/{E2E_DATABASE}"
    )
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


def _parse_pg_url(url: str) -> tuple[str, str, str]:
    normalized = url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    host = parsed.hostname or ""
    port = str(parsed.port or "")
    db = (parsed.path or "").lstrip("/")
    return host, port, db


def validate_e2e_target_config(port: str) -> None:
    """Проверка конфигурации до подключения и DDL."""
    if os.environ.get("APP_ENV") != "test":
        raise RuntimeError("E2E разрешена только при APP_ENV=test")
    if port not in ALLOWED_PG_PORTS:
        raise RuntimeError(f"E2E TEST_PG_PORT должен быть 5432 или 5433, получено {port!r}")
    if not re.fullmatch(r"\d+", port):
        raise RuntimeError(f"Некорректный TEST_PG_PORT: {port!r}")

    app_url = os.environ.get("DATABASE_URL", "")
    worker_url = os.environ.get("WORKER_DATABASE_URL", "")
    migration_url = os.environ.get("MIGRATION_DATABASE_URL", "")

    for key, url in zip(_URL_KEYS, (app_url, worker_url, migration_url), strict=True):
        if not url:
            raise RuntimeError(f"E2E: не задан {key}")
        host, url_port, db = _parse_pg_url(url)
        if host != E2E_HOST:
            raise RuntimeError(f"E2E {key}: host должен быть {E2E_HOST}, получено {host!r}")
        if url_port != port:
            raise RuntimeError(f"E2E {key}: port должен быть {port}, получено {url_port!r}")
        if db != E2E_DATABASE:
            raise RuntimeError(f"E2E {key}: database должна быть {E2E_DATABASE}, получено {db!r}")

    app_host, app_port, app_db = _parse_pg_url(app_url)
    worker_host, worker_port, worker_db = _parse_pg_url(worker_url)
    mig_host, mig_port, mig_db = _parse_pg_url(migration_url)
    if not (app_host == worker_host == mig_host == E2E_HOST):
        raise RuntimeError("E2E: app/worker/migration host не совпадают")
    if not (app_port == worker_port == mig_port == port):
        raise RuntimeError("E2E: app/worker/migration port не совпадают")
    if not (app_db == worker_db == mig_db == E2E_DATABASE):
        raise RuntimeError("E2E: app/worker/migration database не совпадают")


def verify_live_finpilot_test(port: str) -> None:
    """Live-проверка фактической БД после создания."""
    from sqlalchemy import create_engine, text

    url = f"postgresql+psycopg://{E2E_HOST}:{port}/{E2E_DATABASE}"
    engine = create_engine(url)
    with engine.connect() as conn:
        name = conn.execute(text("SELECT current_database()")).scalar_one()
    engine.dispose()
    if name != E2E_DATABASE:
        raise RuntimeError(f"E2E разрешена только {E2E_DATABASE}, подключено к {name!r}")


def assert_finpilot_test_only(port: str) -> None:
    """Guard для API: конфигурация + live target (БД уже должна существовать)."""
    validate_e2e_target_config(port)
    verify_live_finpilot_test(port)
