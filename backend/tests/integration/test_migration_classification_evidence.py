import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from alembic.util.exc import CommandError
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import BACKEND

HEAD = "20261022_0016"
PREV = "20261021_0015"


@pytest.fixture(autouse=True)
def _guard_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


def _alembic_config() -> Config:
    return Config(str(BACKEND / "alembic.ini"))


def _current_revision(engine) -> str | None:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _run_alembic(action: str, revision: str) -> None:
    config = _alembic_config()
    previous = os.getcwd()
    os.chdir(BACKEND)
    try:
        if action == "upgrade":
            command.upgrade(config, revision)
        else:
            command.downgrade(config, revision)
    finally:
        os.chdir(previous)


@pytest.fixture
def restore_head(migrated_database):
    yield
    if _current_revision(migrated_database) != HEAD:
        _run_alembic("upgrade", "head")


def test_migration_sql_not_valid_and_downgrade_guard(migrated_database, restore_head) -> None:
    upgrade_sql = (BACKEND / "alembic" / "sql" / "0016_classification_evidence.sql").read_text(
        encoding="utf-8"
    )
    assert "NOT VALID" in upgrade_sql
    assert "VALIDATE CONSTRAINT cash_transactions_rule_evidence_pair_ck" in upgrade_sql
    assert "VALIDATE CONSTRAINT cash_transactions_classification_rule_fk" in upgrade_sql
    assert "ON DELETE RESTRICT" in upgrade_sql
    assert "CREATE INDEX CONCURRENTLY" not in upgrade_sql
    downgrade_sql = (
        BACKEND / "alembic" / "sql" / "0016_classification_evidence_downgrade.sql"
    ).read_text(encoding="utf-8")
    assert "downgrade_blocked" in downgrade_sql
    assert _current_revision(migrated_database) == HEAD

    tenant_id = uuid.uuid4()
    company_id = uuid.uuid4()
    wallet_id = uuid.uuid4()
    tx_id = uuid.uuid4()
    rule_id = uuid.uuid4()
    user_id = uuid.uuid4()
    with migrated_database.begin() as connection:
        connection.execute(
            text("INSERT INTO tenants (id, name, created_at) VALUES (:id, 't', now())"),
            {"id": tenant_id},
        )
        email = f"m-{uuid.uuid4().hex}@example.com"
        connection.execute(
            text(
                "INSERT INTO users (id, email, normalized_email, password_hash, name, created_at) "
                "VALUES (:id, :email, :email, 'x', 'u', now())"
            ),
            {"id": user_id, "email": email},
        )
        connection.execute(
            text(
                "INSERT INTO companies "
                "(id, tenant_id, name, kind, timezone, created_at, updated_at) "
                "VALUES (:id, :t, 'c', 'company', 'Europe/Moscow', now(), now())"
            ),
            {"id": company_id, "t": tenant_id},
        )
        connection.execute(
            text(
                "INSERT INTO wallets "
                "(id, tenant_id, company_id, name, type, availability_type, created_at) "
                "VALUES (:id, :t, :c, 'w', 'bank', 'spendable', now())"
            ),
            {"id": wallet_id, "t": tenant_id, "c": company_id},
        )
        connection.execute(
            text(
                "INSERT INTO classification_rules "
                "(id, tenant_id, company_id, name, priority, conditions_json, actions_json, "
                "enabled, version, created_at) "
                "VALUES (:id, :t, :c, 'r', 1, '{}'::jsonb, "
                "'{\"category_code\": \"operating\"}'::jsonb, true, 1, now())"
            ),
            {"id": rule_id, "t": tenant_id, "c": company_id},
        )
        connection.execute(
            text(
                "INSERT INTO cash_transactions "
                "(id, tenant_id, company_id, wallet_id, business_date, direction, amount, "
                "currency, description, source, status, classification_origin, "
                "locked_classification, "
                "created_by, version, created_at, updated_at, "
                "classification_rule_id, classification_rule_version) "
                "VALUES (:id, :t, :c, :w, '2026-01-01', 'in', 1.00, 'RUB', 'x', 'manual', "
                "'posted', 'rule', false, :u, 1, now(), now(), :rid, 1)"
            ),
            {
                "id": tx_id,
                "t": tenant_id,
                "c": company_id,
                "w": wallet_id,
                "u": user_id,
                "rid": rule_id,
            },
        )

    with pytest.raises((CommandError, ProgrammingError), match="downgrade_blocked"):
        command.downgrade(_alembic_config(), PREV)
    assert _current_revision(migrated_database) == HEAD

    with migrated_database.begin() as connection:
        connection.execute(
            text(
                "UPDATE cash_transactions SET classification_rule_id = NULL, "
                "classification_rule_version = NULL WHERE id = :id"
            ),
            {"id": tx_id},
        )

    command.downgrade(_alembic_config(), PREV)
    assert _current_revision(migrated_database) == PREV
    command.upgrade(_alembic_config(), HEAD)
    assert _current_revision(migrated_database) == HEAD
