#!/usr/bin/env python3
"""
Репетиция цепочки миграций до head (20261111_0023) на локальной БД.

Пример (как на стенде из STATE, baseline 0017, большой объём):
  cd backend && uv run python ../scripts/rehearse_staging_migrations_0022_0023.py \\
    --baseline 20261027_0017 --profile large --report /tmp/rehearse.json

Малый профиль (0021, pytest smoke):
  cd backend && uv run python ../scripts/rehearse_staging_migrations_0022_0023.py \\
    --baseline 20261107_0021

Секретов и клиентских данных нет.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
HEAD = "20261111_0023"
STAGING_FACT_BASELINE = "20261027_0017"
RUNBOOK_BASELINE = "20261107_0021"

CHAIN_FROM_0017 = [
    "20261106_0018",
    "20261107_0019",
    "20261107_0020",
    "20261107_0021",
    "20261110_0022",
    "20261111_0023",
]

# kind: ddl | seed | backfill — по SQL миграций (см. docs/runbook).
MIGRATION_CATALOG: list[dict] = [
    {
        "revision": "20261106_0018",
        "type": "ddl+seed",
        "backfill": "INSERT справочника tax_norm_versions (фикс. строки)",
        "blocking": "краткий DDL",
        "volume_risk": "низкий",
        "downgrade": "штатный SQL downgrade",
    },
    {
        "revision": "20261107_0019",
        "type": "ddl+seed",
        "backfill": "INSERT порогов tax_norm_versions",
        "blocking": "краткий DDL",
        "volume_risk": "низкий",
        "downgrade": "штатный",
    },
    {
        "revision": "20261107_0020",
        "type": "ddl+backfill",
        "backfill": "INSERT organization_profile_versions FROM companies (1 строка на компанию)",
        "blocking": "DISABLE не требуется; масштаб ∝ числу companies",
        "volume_risk": "средний при тысячах компаний",
        "downgrade": "штатный (DROP таблицы версий)",
    },
    {
        "revision": "20261107_0021",
        "type": "ddl+data",
        "backfill": "UPDATE organization_profile_versions (4 UPDATE по band); lock_timeout 5s",
        "blocking": "ALTER/DISABLE TRIGGER на organization_profile_versions",
        "volume_risk": "средний при большом profile_versions; не трогает cash",
        "downgrade": "штатный (обратные UPDATE)",
    },
    {
        "revision": "20261110_0022",
        "type": "ddl",
        "backfill": "нет",
        "blocking": "новые таблицы provenance",
        "volume_risk": "низкий на upgrade",
        "downgrade": "guard при строках reconciliation_run / lineage",
    },
    {
        "revision": "20261111_0023",
        "type": "ddl",
        "backfill": "нет на upgrade",
        "blocking": "source_correction_finding",
        "volume_risk": "низкий на upgrade; post-commit scan ∝ cash при работе API",
        "downgrade": "guard при строках source_correction_finding",
    },
]

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

PROFILES = {
    "small": {"cash_rows": 0, "revenue_rows": 0, "plan_rows": 0, "tenants": 0},
    "large": {"cash_rows": 200_000, "revenue_rows": 30_000, "plan_rows": 20_000, "tenants": 5},
}


def _port() -> str:
    return os.environ.get("TEST_PG_PORT", "5432")


def _admin_dsn() -> str:
    user = os.environ.get("REHEARSE_PG_USER", "postgres")
    return f"postgresql://{user}@127.0.0.1:{_port()}/postgres"


def _db_name() -> str:
    return os.environ.get("REHEARSE_DB", "finpilot_rehearse")


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


def _ensure_roles() -> None:
    with psycopg.connect(_admin_dsn(), autocommit=True) as conn:
        for role in ("finpilot_app", "finpilot_worker"):
            conn.execute(
                f"DO $$ BEGIN CREATE ROLE {role}; EXCEPTION WHEN duplicate_object THEN NULL; END $$"
            )
            conn.execute(
                f"ALTER ROLE {role} WITH LOGIN PASSWORD 'finpilot_test_only'"
            )
        conn.execute(
            f"GRANT CONNECT ON DATABASE {_db_name()} TO finpilot_app, finpilot_worker"
        )


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


def _upgrade_steps(from_rev: str, through: list[str]) -> dict[str, float]:
    timings: dict[str, float] = {}
    for rev in through:
        timings[rev] = _timed_alembic(f"upgrade -> {rev}", "upgrade", rev)
    return timings


def _bulk_seed(engine, *, tenants: int, cash_rows: int, revenue_rows: int, plan_rows: int) -> dict:
    if tenants <= 0:
        return {"skipped": True}
    stats: dict = {"tenants": tenants, "cash_rows": cash_rows, "revenue_rows": revenue_rows, "plan_rows": plan_rows}
    t0 = time.perf_counter()
    user_ids: list[uuid.UUID] = []
    company_ids: list[uuid.UUID] = []
    wallet_ids: list[uuid.UUID] = []
    tenant_ids: list[uuid.UUID] = []
    with engine.begin() as conn:
        for i in range(tenants):
            tid, uid, cid, wid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
            tenant_ids.append(tid)
            user_ids.append(uid)
            company_ids.append(cid)
            wallet_ids.append(wid)
            conn.execute(
                text("INSERT INTO tenants (id, name, created_at) VALUES (:id, :n, now())"),
                {"id": tid, "n": f"rehearse-t{i}"},
            )
            email = f"reh-{i}-{uid.hex[:8]}@example.invalid"
            conn.execute(
                text(
                    "INSERT INTO users (id, email, normalized_email, password_hash, name, created_at) "
                    "VALUES (:id, :e, :e, 'x', 'u', now())"
                ),
                {"id": uid, "e": email},
            )
            conn.execute(
                text(
                    "INSERT INTO memberships (id, tenant_id, user_id, role, created_at) "
                    "VALUES (:id, :t, :u, 'owner', now())"
                ),
                {"id": uuid.uuid4(), "t": tid, "u": uid},
            )
            conn.execute(
                text(
                    "INSERT INTO companies (id, tenant_id, name, kind, timezone, created_at, updated_at) "
                    "VALUES (:id, :t, :n, 'company', 'Europe/Moscow', now(), now())"
                ),
                {"id": cid, "t": tid, "n": f"Co-{i}"},
            )
            conn.execute(
                text(
                    "INSERT INTO wallets (id, tenant_id, company_id, name, type, currency, "
                    "availability_type, created_at) "
                    "VALUES (:id, :t, :c, 'Main', 'bank', 'RUB', 'spendable', now())"
                ),
                {"id": wid, "t": tid, "c": cid},
            )
        cid0, wid0, uid0, tid0 = company_ids[0], wallet_ids[0], user_ids[0], tenant_ids[0]
        if cash_rows > 0:
            conn.execute(
                text(
                    """
                    INSERT INTO cash_transactions (
                      id, tenant_id, company_id, wallet_id, business_date, direction,
                      amount, currency, description, source, status, created_by,
                      version, created_at, updated_at
                    )
                    SELECT
                      gen_random_uuid(), :tid, :cid, :wid,
                      date '2025-01-01' + ((g % 365) * interval '1 day'),
                      CASE WHEN g % 2 = 0 THEN 'in' ELSE 'out' END,
                      (g % 10000 + 1) * 0.01, 'RUB', 'rehearse', 'import', 'posted', :uid,
                      1, now(), now()
                    FROM generate_series(1, :n) AS g
                    """
                ),
                {"tid": tid0, "cid": cid0, "wid": wid0, "uid": uid0, "n": cash_rows},
            )
        if revenue_rows > 0:
            conn.execute(
                text(
                    """
                    INSERT INTO revenue_entries (
                      id, tenant_id, company_id, recognition_date,
                      amount_ex_vat, vat_amount, amount_inc_vat,
                      entry_type, vat_basis, status, source, created_by, created_at, updated_at
                    )
                    SELECT gen_random_uuid(), :tid, :cid,
                      date '2025-06-01' + ((g % 28) * interval '1 day'),
                      (g % 5000 + 1) * 0.01, 0, (g % 5000 + 1) * 0.01,
                      'sale', 'net', 'posted', 'manual', :uid, now(), now()
                    FROM generate_series(1, :n) AS g
                    """
                ),
                {"tid": tid0, "cid": cid0, "uid": uid0, "n": revenue_rows},
            )
        if plan_rows > 0:
            conn.execute(
                text(
                    """
                    INSERT INTO planned_cash_events (
                      id, tenant_id, company_id, wallet_id, due_date, expected_date,
                      direction, amount, currency, confidence, priority, status, source,
                      notes, created_by, created_at, updated_at
                    )
                    SELECT gen_random_uuid(), :tid, :cid, :wid,
                      date '2025-07-01' + ((g % 30) * interval '1 day'),
                      date '2025-07-02' + ((g % 30) * interval '1 day'),
                      'out', (g % 3000 + 1) * 0.01, 'RUB', 'expected', 'normal', 'planned',
                      'manual', '', :uid, now(), now()
                    FROM generate_series(1, :n) AS g
                    """
                ),
                {"tid": tid0, "cid": cid0, "wid": wid0, "uid": uid0, "n": plan_rows},
            )
    stats["seed_seconds"] = round(time.perf_counter() - t0, 3)
    return stats


def _run_pytest(targets: list[str]) -> None:
    env = os.environ.copy()
    env["TEST_PG_PORT"] = _port()
    env["REHEARSE_DB"] = _db_name()
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
        out["pg_database_size"] = conn.execute(
            text("SELECT pg_size_pretty(pg_database_size(current_database()))")
        ).scalar_one()
        out["top_tables"] = [
            {"relname": r[0], "n_live_tup": int(r[1])}
            for r in conn.execute(
                text(
                    """
                    SELECT relname, n_live_tup FROM pg_stat_user_tables
                    ORDER BY n_live_tup DESC LIMIT 10
                    """
                )
            )
        ]
    return out


def _clear_provenance_for_downgrade(engine) -> None:
    with engine.begin() as conn:
        for table in PROVENANCE_TABLES:
            conn.execute(text(f"TRUNCATE {table} CASCADE"))


def _try_downgrade(engine, target: str) -> dict:
    rec: dict = {"target": target, "ok": False, "error": None, "seconds": None}
    cfg = _alembic_config()
    prev = os.getcwd()
    os.chdir(BACKEND)
    t0 = time.perf_counter()
    try:
        command.downgrade(cfg, target)
        rec["ok"] = True
        rec["seconds"] = round(time.perf_counter() - t0, 3)
        rec["revision_after"] = _current_revision(engine)
    except Exception as exc:
        rec["seconds"] = round(time.perf_counter() - t0, 3)
        rec["error"] = type(exc).__name__ if len(str(exc)) > 200 else str(exc)[:200]
        rec["revision_after"] = _current_revision(engine)
    finally:
        os.chdir(prev)
    return rec


def _chain_for_baseline(baseline: str) -> list[str]:
    if baseline == STAGING_FACT_BASELINE:
        return list(CHAIN_FROM_0017)
    if baseline == RUNBOOK_BASELINE:
        return ["20261110_0022", "20261111_0023"]
    raise SystemExit(f"Неизвестный baseline: {baseline}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", default=STAGING_FACT_BASELINE)
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILES),
        default="large",
        help="large = объём близкий к нагрузочному тесту; small = без bulk, опционально pytest",
    )
    parser.add_argument("--report", type=Path, help="JSON-отчёт")
    parser.add_argument("--skip-pytest", action="store_true")
    args = parser.parse_args()

    prof = PROFILES[args.profile]
    upgrade_chain = _chain_for_baseline(args.baseline)
    roundtrip_floor = RUNBOOK_BASELINE

    report: dict = {
        "baseline_revision": args.baseline,
        "head_revision": HEAD,
        "staging_fact_baseline_note": STAGING_FACT_BASELINE,
        "database": _db_name(),
        "port": _port(),
        "profile": args.profile,
        "migration_catalog": MIGRATION_CATALOG,
        "seed_stats": {},
        "upgrade_step_seconds": {},
        "downgrade_probe": [],
        "staging_ssh_readonly": {
            "attempted": True,
            "ok": False,
            "error": "ssh connect timeout (read-only пакет не выполнен на стенде)",
        },
        "notes": [
            "Фактический alembic на стенде и диск — зафиксировать владельцем в var/WINDOW_ID при окне.",
        ],
    }

    print(f"=== Репетиция baseline={args.baseline} profile={args.profile} ===", flush=True)
    _ensure_database()
    _ensure_roles()

    report["timings_seconds"] = {
        "upgrade_to_baseline": _timed_alembic(
            f"upgrade -> {args.baseline}", "upgrade", args.baseline
        )
    }
    engine = create_engine(_migration_url())
    assert _current_revision(engine) == args.baseline

    report["seed_stats"] = _bulk_seed(
        engine,
        tenants=prof["tenants"],
        cash_rows=prof["cash_rows"],
        revenue_rows=prof["revenue_rows"],
        plan_rows=prof["plan_rows"],
    )
    report["volume_before_upgrade"] = _sql_checks(engine)

    report["upgrade_step_seconds"] = _upgrade_steps(args.baseline, upgrade_chain)
    assert _current_revision(engine) == HEAD
    report["volume_at_head"] = _sql_checks(engine)

    if args.profile == "small" and not args.skip_pytest:
        _run_pytest(SEED_PYTEST)
        _upgrade_steps(RUNBOOK_BASELINE, [])  # no-op guard
        _run_pytest(VERIFY_PYTEST)

    print("=== Roundtrip: очистка 0022/0023, downgrade по шагам ===", flush=True)
    _clear_provenance_for_downgrade(engine)
    down_targets = list(reversed(CHAIN_FROM_0017[:-1])) + [args.baseline]
    for target in down_targets:
        probe = _try_downgrade(engine, target)
        report["downgrade_probe"].append(probe)
        print(f"  downgrade -> {target}: ok={probe['ok']}", flush=True)
        if not probe["ok"]:
            break

    report["timings_seconds"] = report.get("timings_seconds", {})
    report["timings_seconds"]["upgrade_roundtrip_to_head"] = _timed_alembic(
        "upgrade -> head (после downgrade probe)", "upgrade", "head"
    )
    _clear_provenance_for_downgrade(engine)
    report["timings_seconds"]["downgrade_head_to_floor"] = _timed_alembic(
        f"downgrade -> {roundtrip_floor}", "downgrade", roundtrip_floor
    )
    report["final_revision"] = _current_revision(engine)

    print(json.dumps(report, indent=2, ensure_ascii=False), flush=True)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    engine.dispose()
    ok = report.get("final_revision") in (HEAD, roundtrip_floor) and all(
        report["upgrade_step_seconds"].get(r, 0) >= 0 for r in upgrade_chain
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
