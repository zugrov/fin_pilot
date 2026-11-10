import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from tests.integration.test_balances_dataset_migration import _alembic_config, _current_revision

HEAD = "20261110_0022"
PREV = "20261107_0021"


@pytest.fixture(autouse=True)
def _at_head(migrated_database):
    if _current_revision(migrated_database) != HEAD:
        command.upgrade(_alembic_config(), "head")


def test_upgrade_head_is_fa_r033(migrated_database) -> None:
    rev = _current_revision(migrated_database)
    assert rev in (HEAD, "20261111_0023")


def test_downgrade_blocked_with_reconciliation_run(migrated_database) -> None:
    tenant_id = uuid.uuid4()
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()
    with migrated_database.begin() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name, created_at) VALUES (:id, 't', now())"),
            {"id": tenant_id},
        )
        email = f"r-{uuid.uuid4().hex}@example.com"
        conn.execute(
            text(
                "INSERT INTO users (id, email, normalized_email, password_hash, name, created_at) "
                "VALUES (:id, :email, :email, 'x', 'u', now())"
            ),
            {"id": user_id, "email": email},
        )
        conn.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at) "
                "VALUES (:id, :t, :u, 'owner', now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "u": user_id},
        )
        conn.execute(
            text(
                "INSERT INTO companies "
                "(id, tenant_id, name, kind, timezone, created_at, updated_at) "
                "VALUES (:id, :t, 'c', 'company', 'Europe/Moscow', now(), now())"
            ),
            {"id": company_id, "t": tenant_id},
        )
        conn.execute(
            text(
                "INSERT INTO reconciliation_run "
                "(id, tenant_id, company_id, run_kind, period_year, period_month, "
                "input_fingerprints, input_hashes, metrics, group_refs, engine_version, "
                "created_by_user_id, created_at) "
                "VALUES (:id, :t, :c, 'bank_card_51', 2026, 8, '[]'::jsonb, '{}'::jsonb, "
                "'{}'::jsonb, '[]'::jsonb, 'test', :u, now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "c": company_id, "u": user_id},
        )
    config: Config = _alembic_config()
    with pytest.raises(Exception, match="downgrade_blocked"):
        command.downgrade(config, PREV)


def test_downgrade_upgrade_roundtrip_empty(migrated_database) -> None:
    config = _alembic_config()
    command.downgrade(config, PREV)
    assert _current_revision(migrated_database) == PREV
    command.upgrade(config, HEAD)
    assert _current_revision(migrated_database) == HEAD
    command.upgrade(config, "head")
