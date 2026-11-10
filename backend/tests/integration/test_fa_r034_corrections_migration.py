import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from tests.integration.conftest import FA_R033_MIGRATION_REVISION, HEAD_REVISION
from tests.integration.test_balances_dataset_migration import _alembic_config, _current_revision

PREV = FA_R033_MIGRATION_REVISION


@pytest.fixture(autouse=True)
def _at_head(migrated_database):
    if _current_revision(migrated_database) != HEAD_REVISION:
        command.upgrade(_alembic_config(), "head")


def test_upgrade_head_is_repo_head(migrated_database) -> None:
    assert _current_revision(migrated_database) == HEAD_REVISION


def test_downgrade_blocked_with_correction_finding(migrated_database) -> None:
    tenant_id = uuid.uuid4()
    company_id = uuid.uuid4()
    with migrated_database.begin() as conn:
        conn.execute(
            text("INSERT INTO tenants (id, name, created_at) VALUES (:id, 't', now())"),
            {"id": tenant_id},
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
                "INSERT INTO source_correction_finding "
                "(id, tenant_id, company_id, kind, severity, created_at) "
                "VALUES (:id, :t, :c, 'period_overlap', 'warning', now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "c": company_id},
        )
    config: Config = _alembic_config()
    with pytest.raises(Exception, match="downgrade_blocked"):
        command.downgrade(config, PREV)


def test_downgrade_upgrade_roundtrip_empty(migrated_database) -> None:
    config = _alembic_config()
    command.downgrade(config, PREV)
    assert _current_revision(migrated_database) == PREV
    command.upgrade(config, HEAD_REVISION)
    assert _current_revision(migrated_database) == HEAD_REVISION
