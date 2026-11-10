"""Retention: app_expire_reconciliation_runs."""

import os
import uuid
from datetime import UTC, datetime

from app.services.reconciliation_run_service import expire_reconciliation_runs
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def _insert_run(admin, *, tenant_id, company_id, user_id, created_at: datetime) -> uuid.UUID:
    run_id = uuid.uuid4()
    with admin.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )
        connection.execute(
            text(
                "INSERT INTO reconciliation_run "
                "(id, tenant_id, company_id, run_kind, period_year, period_month, "
                "input_fingerprints, input_hashes, metrics, group_refs, engine_version, "
                "created_by_user_id, created_at) "
                "VALUES (:id, :t, :c, 'bank_card_51', 2026, 1, '[]'::jsonb, '{}'::jsonb, "
                "'{}'::jsonb, '[]'::jsonb, 'test', :u, :at)"
            ),
            {
                "id": run_id,
                "t": tenant_id,
                "c": company_id,
                "u": user_id,
                "at": created_at,
            },
        )
    return run_id


def _minimal_tenant(admin) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    with admin.begin() as connection:
        connection.execute(
            text("INSERT INTO tenants (id, name, created_at) VALUES (:id, 't', now())"),
            {"id": tenant_id},
        )
        email = f"ret-{uuid.uuid4().hex}@example.com"
        connection.execute(
            text(
                "INSERT INTO users (id, email, normalized_email, password_hash, name, created_at) "
                "VALUES (:id, :email, :email, 'x', 'u', now())"
            ),
            {"id": user_id, "email": email},
        )
        connection.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at) "
                "VALUES (:id, :t, :u, 'owner', now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "u": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO companies "
                "(id, tenant_id, name, kind, timezone, created_at, updated_at) "
                "VALUES (:id, :t, 'c', 'company', 'Europe/Moscow', now(), now())"
            ),
            {"id": company_id, "t": tenant_id},
        )
    return tenant_id, company_id, user_id


def test_expire_reconciliation_runs_respects_age_and_tenants(admin, migrated_database) -> None:
    old_at = datetime(2020, 1, 15, tzinfo=UTC)
    recent_at = datetime(2025, 6, 1, tzinfo=UTC)
    cutoff = datetime(2024, 1, 1, tzinfo=UTC)

    t1, c1, u1 = _minimal_tenant(admin)
    t2, c2, u2 = _minimal_tenant(admin)
    old_a = _insert_run(admin, tenant_id=t1, company_id=c1, user_id=u1, created_at=old_at)
    recent_a = _insert_run(admin, tenant_id=t1, company_id=c1, user_id=u1, created_at=recent_at)
    old_b = _insert_run(admin, tenant_id=t2, company_id=c2, user_id=u2, created_at=old_at)
    recent_b = _insert_run(admin, tenant_id=t2, company_id=c2, user_id=u2, created_at=recent_at)

    with admin.connect() as connection:
        due = connection.execute(
            text(
                "SELECT count(*) FROM reconciliation_run WHERE created_at < :cutoff"
            ),
            {"cutoff": cutoff},
        ).scalar_one()
    assert int(due) == 2

    worker_engine = create_engine(os.environ["WORKER_DATABASE_URL"])
    worker_session = sessionmaker(bind=worker_engine)()
    try:
        from app.config import get_settings

        removed = expire_reconciliation_runs(
            worker_session, get_settings(), before=cutoff, limit=500
        )
        worker_session.commit()
    finally:
        worker_session.close()
    assert int(removed) == 2

    with admin.connect() as connection:
        remaining = {
            row[0]
            for row in connection.execute(
                text("SELECT id FROM reconciliation_run")
            ).fetchall()
        }
    assert old_a not in remaining
    assert old_b not in remaining
    assert recent_a in remaining
    assert recent_b in remaining

    app_engine = create_engine(os.environ["DATABASE_URL"])
    with app_engine.connect() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(t2)},
        )
        visible = connection.execute(
            text("SELECT count(*) FROM reconciliation_run")
        ).scalar_one()
    assert int(visible) == 1
