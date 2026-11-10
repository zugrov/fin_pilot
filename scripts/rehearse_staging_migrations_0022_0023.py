#!/usr/bin/env python3
"""
Репетиция миграций 20261110_0022 и 20261111_0023 на локальной БД (без staging/SSH).

Требования: Postgres 16 на 127.0.0.1, порт TEST_PG_PORT (по умолчанию 5432), trust/superuser
для CREATE DATABASE (как в CI: postgres@127.0.0.1:5433).

Базовая ревизия: STAGING_BASELINE_REVISION = 20261107_0021 (runbook до окна; см. STATE
для исторического факта стенда — может быть ниже, тогда upgrade head на стенде пройдёт
цепочку 0018…0023).

Секретов и клиентских данных нет. Пишет отчёт в stdout и опционально --report PATH.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
STAGING_BASELINE = "20261107_0021"
ROUNDTRIP_FLOOR = "20261107_0021"
HEAD = "20261111_0023"

PROVENANCE_TABLES = (
    "source_correction_finding",
    "import_row_lineage",
    "import_source_fingerprints",
    "reconciliation_run",
)

SEED_PYTEST = [
    "tests/integration/test_import_api.py::test_i1_repeat_file_creates_nothing_new",
    "tests/integration/test_import_api.py::test_i3_bank_and_clientbank_share_one_transaction",
]

VERIFY_PYTEST = [
    "tests/integration/test_fa_r033_provenance_import.py",
    "tests/integration/test_fa_r034_corrections_import.py",
]


def _port() -> str:
    return os.environ.get("TEST_PG_PORT", "5432")


def _admin_dsn() -> str:
    user = os.environ.get("REHEARSE_PG_USER", "postgres")
    return f"postgresql://{user}@127.0.0.1:{_port()}/postgres"


def _db_name() -> str:
    return os.environ.get("REHEARSE_DB", "finpilot_test")


def _migration_url() -> str:
    return f"postgresql+psycopg://127.0.0.1:{_port()}/{_db_name()}"


def _alembic_config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    os.environ["MIGRATION_DATABASE_URL"] = _migration_url()
    return cfg


def _ensure_database() -> None:
    name = _db_name()
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
        ).fetchone()
        if exists:
            conn.execute(
                psycopg.sql.SQL("DROP DATABASE {} WITH (FORCE)").format(
                    psycopg.sql.Identifier(name)
                )
            )
        conn.execute(psycopg.sql.SQL("CREATE DATABASE {}").format(psycopg.sql.Identifier(name)))


def _current_revision(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _timed_alembic(label: str, op: str, revision: str) -> float:
    cfg = _alembic_config()
    prev = os.getcwd()
    os.chdir(BACKEND)
    t0 = time.perf_counter()
    try:
        if op == "upgrade":
            command.upgrade(cfg, revision)
        else:
            command.downgrade(cfg, revision)
    finally:
        os.chdir(prev)
    elapsed = time.perf_counter() - t0
    print(f"[timing] {label}: {elapsed:.3f}s", flush=True)
    return elapsed


def _run_pytest(targets: list[str]) -> None:
    env = os.environ.copy()
    env["TEST_PG_PORT"] = _port()
    env["APP_ENV"] = "test"
    env["DATABASE_URL"] = (
        f"postgresql+psycopg://finpilot_app:finpilot_test_only@127.0.0.1:{_port()}/{_db_name()}"
    )
    env["WORKER_DATABASE_URL"] = (
        f"postgresql+psycopg://finpilot_worker:finpilot_test_only@127.0.0.1:{_port()}/{_db_name()}"
    )
    env["MIGRATION_DATABASE_URL"] = _migration_url()
    cmd = ["uv", "run", "pytest", "-q", *targets]
    subprocess.run(cmd, cwd=BACKEND, env=env, check=True)


def _sql_checks(engine) -> dict:
    out: dict = {}
    with engine.connect() as conn:
        out["alembic_version"] = _current_revision(engine)
        regs = conn.execute(
            text(
                """
                SELECT to_regclass('public.import_source_fingerprints'),
                       to_regclass('public.import_row_lineage'),
                       to_regclass('public.reconciliation_run'),
                       to_regclass('public.source_correction_finding')
                """
            )
        ).one()
        out["tables_present"] = all(r is not None for r in regs)
        rls = conn.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relname = ANY(:names)
                """
            ),
            {
                "names": [
                    "import_source_fingerprints",
                    "import_row_lineage",
                    "reconciliation_run",
                    "source_correction_finding",
                ]
            },
        ).fetchall()
        out["rls_enabled"] = all(r[1] and r[2] for r in rls) and len(rls) == 4
        grants = conn.execute(
            text(
                """
                SELECT DISTINCT grantee, table_name
                FROM information_schema.role_table_grants
                WHERE table_name IN (
                  'import_source_fingerprints',
                  'import_row_lineage',
                  'source_correction_finding'
                )
                  AND grantee IN ('finpilot_app', 'finpilot_worker')
                """
            )
        ).fetchall()
        out["grant_rows"] = len(grants)
        out["correction_findings"] = conn.execute(
            text("SELECT count(*) FROM source_correction_finding")
        ).scalar_one()
    return out


def _clear_provenance_for_downgrade(engine) -> None:
    with engine.begin() as conn:
        for table in PROVENANCE_TABLES:
            conn.execute(text(f"TRUNCATE {table} CASCADE"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="JSON-отчёт")
    parser.add_argument("--skip-pytest", action="store_true", help="Только alembic/SQL")
    args = parser.parse_args()

    report: dict = {
        "staging_baseline_revision": STAGING_BASELINE,
        "head_revision": HEAD,
        "database": _db_name(),
        "port": _port(),
        "timings_seconds": {},
        "checks_after_upgrade": {},
        "checks_after_roundtrip": {},
        "notes": [],
    }

    print("=== Репетиция миграций 0022/0023 ===", flush=True)
    _ensure_database()

    report["timings_seconds"]["upgrade_baseline"] = _timed_alembic(
        f"upgrade -> {STAGING_BASELINE}",
        "upgrade",
        STAGING_BASELINE,
    )
    engine = create_engine(_migration_url())
    assert _current_revision(engine) == STAGING_BASELINE

    if not args.skip_pytest:
        print("=== Seed (импорты cash, два сценария) ===", flush=True)
        _run_pytest(SEED_PYTEST)

    report["timings_seconds"]["upgrade_0021_to_head"] = _timed_alembic(
        "upgrade 0021 -> head",
        "upgrade",
        "head",
    )
    assert _current_revision(engine) == HEAD
    report["checks_after_upgrade"] = _sql_checks(engine)

    if not args.skip_pytest:
        print("=== Smoke: provenance + corrections ===", flush=True)
        _run_pytest(VERIFY_PYTEST)
        report["checks_after_upgrade"] = _sql_checks(engine)

    print("=== Roundtrip с сохранением legacy-данных (очистка только 0022/0023 таблиц) ===", flush=True)
    _clear_provenance_for_downgrade(engine)
    report["timings_seconds"]["downgrade_head_to_0021"] = _timed_alembic(
        f"downgrade -> {ROUNDTRIP_FLOOR}",
        "downgrade",
        ROUNDTRIP_FLOOR,
    )
    assert _current_revision(engine) == ROUNDTRIP_FLOOR
    report["timings_seconds"]["upgrade_roundtrip_to_head"] = _timed_alembic(
        "upgrade roundtrip -> head",
        "upgrade",
        "head",
    )
    report["checks_after_roundtrip"] = _sql_checks(engine)

    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    engine.dispose()
    ok = (
        report["checks_after_upgrade"].get("tables_present")
        and report["checks_after_upgrade"].get("rls_enabled")
        and report["checks_after_roundtrip"].get("alembic_version") == HEAD
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
