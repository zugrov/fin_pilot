"""RLS для таблиц FA-R03.3-min (роль finpilot_app, не superuser)."""

import os
import uuid
from uuid import uuid4

import pytest
from app.models.provenance import ImportRowLineage, ImportSourceFingerprint, ReconciliationRun
from app.security.context import set_context
from sqlalchemy import create_engine, select, text
from tests.integration.test_import_api import (
    FIXTURES,
    _commit,
    _ready,
    _source,
    _upload,
)


def _assert_finpilot_app_rls_enforced(admin) -> None:
    with admin.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolbypassrls FROM pg_roles WHERE rolname = 'finpilot_app'"
            )
        ).scalar_one()
    assert role is False


def _policies_cover_tenant_isolation(admin, table: str) -> None:
    with admin.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT policyname, qual::text "
                "FROM pg_policies WHERE tablename = :table"
            ),
            {"table": table},
        ).fetchall()
    assert rows
    assert any("app_tenant()" in (row[1] or "") for row in rows)


def test_provenance_tables_have_tenant_rls_policies(admin, migrated_database) -> None:
    _assert_finpilot_app_rls_enforced(admin)
    for table in (
        "import_source_fingerprints",
        "import_row_lineage",
        "reconciliation_run",
    ):
        _policies_cover_tenant_isolation(admin, table)


def _seed_tenant_runs(admin, tenant_id: uuid.UUID, company_id: uuid.UUID, user_id: uuid.UUID):
    run_id = uuid.uuid4()
    with admin.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO reconciliation_run "
                "(id, tenant_id, company_id, run_kind, period_year, period_month, "
                "input_fingerprints, input_hashes, metrics, group_refs, engine_version, "
                "created_by_user_id, created_at) "
                "VALUES (:id, :t, :c, 'bank_card_51', 2026, 8, '[]'::jsonb, '{}'::jsonb, "
                "'{}'::jsonb, '[]'::jsonb, 'test', :u, now())"
            ),
            {"id": run_id, "t": tenant_id, "c": company_id, "u": user_id},
        )
    return run_id


def _tenant_ids(client, admin, email: str, app, fake, tmp_path) -> tuple[str, str, str]:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, email)
    source = _source(client, company_id, wallet_id)
    content = (FIXTURES / "cash_ok.csv").read_bytes()
    uploaded = _upload(client, company_id, source["id"], content, "cash.csv", uuid4().hex)
    assert _commit(client, uploaded.json()["id"]).status_code == 200
    with admin.connect() as connection:
        tenant_id = connection.execute(
            text("SELECT tenant_id FROM companies WHERE id = :id"),
            {"id": company_id},
        ).scalar_one()
        user_id = connection.execute(
            text(
                "SELECT user_id FROM memberships WHERE tenant_id = :t LIMIT 1"
            ),
            {"t": tenant_id},
        ).scalar_one()
    return str(tenant_id), str(company_id), str(user_id)


def test_other_tenant_cannot_see_provenance_via_app_role(
    client, admin, app, fake, tmp_path
) -> None:
    tenant_a, company_a, user_a = _tenant_ids(
        client, admin, "rls-a@example.com", app, fake, tmp_path
    )
    _seed_tenant_runs(admin, uuid.UUID(tenant_a), uuid.UUID(company_a), uuid.UUID(user_a))

    engine = create_engine(os.environ["DATABASE_URL"])
    foreign_tenant = str(uuid4())
    with engine.connect() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": foreign_tenant},
        )
        fp = connection.execute(
            text("SELECT count(*) FROM import_source_fingerprints")
        ).scalar_one()
        lin = connection.execute(text("SELECT count(*) FROM import_row_lineage")).scalar_one()
        runs = connection.execute(text("SELECT count(*) FROM reconciliation_run")).scalar_one()
    assert int(fp) == 0
    assert int(lin) == 0
    assert int(runs) == 0

    session = app.state.session_factory()
    try:
        set_context(session, tenant_id=uuid.UUID(foreign_tenant), user_id=uuid.uuid4())
        assert session.scalars(select(ImportSourceFingerprint)).all() == []
        assert session.scalars(select(ImportRowLineage)).all() == []
        assert session.scalars(select(ReconciliationRun)).all() == []
    finally:
        session.close()

    with engine.connect() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_a},
        )
        own_fp = connection.execute(
            text("SELECT count(*) FROM import_source_fingerprints")
        ).scalar_one()
        own_runs = connection.execute(
            text("SELECT count(*) FROM reconciliation_run")
        ).scalar_one()
    assert int(own_fp) >= 1
    assert int(own_runs) >= 1


def test_app_cannot_update_reconciliation_run(
    client, admin, app, fake, tmp_path
) -> None:
    tenant_a, company_a, user_a = _tenant_ids(
        client, admin, "rls-upd@example.com", app, fake, tmp_path
    )
    run_id = _seed_tenant_runs(
        admin, uuid.UUID(tenant_a), uuid.UUID(company_a), uuid.UUID(user_a)
    )
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_a},
        )
        with pytest.raises(Exception) as exc:
            connection.execute(
                text(
                    "UPDATE reconciliation_run SET metrics = '{\"x\": 1}'::jsonb "
                    "WHERE id = :id"
                ),
                {"id": run_id},
            )
    message = str(exc.value).lower()
    assert "append-only" in message or "permission denied" in message
