import os
import uuid

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import BACKEND

HEAD = "20261107_0021"
PREV = "20261107_0020"


@pytest.fixture(autouse=True)
def _guard_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


def _run_alembic(action: str, revision: str) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    previous = os.getcwd()
    os.chdir(BACKEND)
    try:
        if action == "upgrade":
            command.upgrade(config, revision)
        else:
            command.downgrade(config, revision)
    finally:
        os.chdir(previous)


def _current_revision(engine) -> str:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


@pytest.fixture
def restore_head(migrated_database):
    yield
    if _current_revision(migrated_database) != HEAD:
        _run_alembic("upgrade", "head")


def test_org_profile_migration_up_down(migrated_database, restore_head) -> None:
    assert _current_revision(migrated_database) == HEAD
    _run_alembic("downgrade", PREV)
    with migrated_database.connect() as connection:
        exists = connection.execute(
            text("SELECT to_regclass('public.organization_profile_versions')")
        ).scalar_one()
    assert exists is not None
    _run_alembic("upgrade", HEAD)
    assert _current_revision(migrated_database) == HEAD


def test_prior_year_band_neutral_migration_roundtrip(migrated_database, restore_head) -> None:
    tenant_id = uuid.uuid4()
    company_id = uuid.uuid4()
    version_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    _run_alembic("downgrade", PREV)
    with migrated_database.begin() as connection:
        connection.execute(
            text("INSERT INTO tenants (id, name, created_at) VALUES (:id, 't', now())"),
            {"id": tenant_id},
        )
        connection.execute(
            text(
                "INSERT INTO users (id, email, normalized_email, password_hash, name, created_at) "
                "VALUES (:id, 'band@x.com', 'band@x.com', 'h', 'u', now())"
            ),
            {"id": owner_id},
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
                """
                INSERT INTO organization_profile_versions (
                  id, tenant_id, company_id, effective_from, prior_year_revenue_band
                ) VALUES (:vid, :t, :c, '2026-01-01', 'from_20m_to_272_5m')
                """
            ),
            {"vid": version_id, "t": tenant_id, "c": company_id},
        )
        connection.execute(
            text(
                """
                UPDATE organization_profile_versions
                SET confirmed_at = now(), confirmed_by = :u, confirmed_role = 'owner'
                WHERE id = :vid
                """
            ),
            {"vid": version_id, "u": owner_id},
        )
    _run_alembic("upgrade", HEAD)
    with migrated_database.connect() as connection:
        band = connection.execute(
            text(
                "SELECT prior_year_revenue_band FROM organization_profile_versions WHERE id = :vid"
            ),
            {"vid": version_id},
        ).scalar_one()
    assert band == "from_threshold_to_cap_5"
    _run_alembic("downgrade", PREV)
    with migrated_database.connect() as connection:
        band = connection.execute(
            text(
                "SELECT prior_year_revenue_band FROM organization_profile_versions WHERE id = :vid"
            ),
            {"vid": version_id},
        ).scalar_one()
    assert band == "from_20m_to_272_5m"
    _run_alembic("upgrade", HEAD)


def test_bootstrap_on_upgrade_after_companies_inserted(migrated_database, restore_head) -> None:
    _run_alembic("downgrade", "20261107_0019")
    tenant_id = uuid.uuid4()
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    with migrated_database.begin() as connection:
        connection.execute(
            text("INSERT INTO tenants (id, name, created_at) VALUES (:id, 't', now())"),
            {"id": tenant_id},
        )
        for cid, created in (
            (company_a, "2026-03-15T10:00:00Z"),
            (company_b, "2026-07-20T10:00:00Z"),
        ):
            connection.execute(
                text(
                    "INSERT INTO companies "
                    "(id, tenant_id, name, kind, timezone, created_at, updated_at) "
                    "VALUES (:id, :t, :n, 'company', 'Europe/Moscow', "
                    "CAST(:c AS timestamptz), CAST(:c AS timestamptz))"
                ),
                {"id": cid, "t": tenant_id, "n": f"c-{cid.hex[:6]}", "c": created},
            )
    _run_alembic("upgrade", HEAD)
    with migrated_database.connect() as connection:
        rows = (
            connection.execute(
                text(
                    """
                SELECT company_id::text, effective_from::text, confirmed_at
                FROM organization_profile_versions
                WHERE company_id IN (:a, :b)
                ORDER BY company_id
                """
                ),
                {"a": company_a, "b": company_b},
            )
            .mappings()
            .all()
        )
    assert len(rows) == 2
    by_company = {r["company_id"]: r for r in rows}
    assert by_company[str(company_a)]["effective_from"] == "2026-03-01"
    assert by_company[str(company_b)]["effective_from"] == "2026-07-01"
    assert all(r["confirmed_at"] is None for r in rows)


def test_effective_from_not_first_of_month_rejected(migrated_database) -> None:
    tenant_id = uuid.uuid4()
    company_id = uuid.uuid4()
    with migrated_database.begin() as connection:
        connection.execute(
            text("INSERT INTO tenants (id, name, created_at) VALUES (:id, 't', now())"),
            {"id": tenant_id},
        )
        connection.execute(
            text(
                "INSERT INTO companies "
                "(id, tenant_id, name, kind, timezone, created_at, updated_at) "
                "VALUES (:id, :t, 'c', 'company', 'Europe/Moscow', now(), now())"
            ),
            {"id": company_id, "t": tenant_id},
        )
        with pytest.raises(DBAPIError):
            connection.execute(
                text(
                    """
                    INSERT INTO organization_profile_versions (
                      id, tenant_id, company_id, effective_from
                    ) VALUES (gen_random_uuid(), :t, :c, '2026-03-15')
                    """
                ),
                {"t": tenant_id, "c": company_id},
            )


@pytest.mark.skip(reason="Закрытие периодов в репозитории отсутствует — enforcement в P2b")
def test_period_close_enforcement_deferred() -> None:
    pass


def test_confirmed_row_immutable_at_db(migrated_database) -> None:
    tenant_id = uuid.uuid4()
    company_id = uuid.uuid4()
    version_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    with migrated_database.begin() as connection:
        connection.execute(
            text("INSERT INTO tenants (id, name, created_at) VALUES (:id, 't', now())"),
            {"id": tenant_id},
        )
        connection.execute(
            text(
                "INSERT INTO users (id, email, normalized_email, password_hash, name, created_at) "
                "VALUES (:id, 'u@x.com', 'u@x.com', 'h', 'u', now())"
            ),
            {"id": owner_id},
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
                """
                INSERT INTO organization_profile_versions (
                  id, tenant_id, company_id, effective_from
                ) VALUES (:vid, :t, :c, '2026-01-01')
                """
            ),
            {"vid": version_id, "t": tenant_id, "c": company_id},
        )
        connection.execute(
            text(
                """
                UPDATE organization_profile_versions
                SET confirmed_at = now(), confirmed_by = :u, confirmed_role = 'owner'
                WHERE id = :vid
                """
            ),
            {"vid": version_id, "u": owner_id},
        )
        with pytest.raises(DBAPIError, match="confirmed_immutable"):
            connection.execute(
                text(
                    "UPDATE organization_profile_versions SET tax_system = 'usn' WHERE id = :vid"
                ),
                {"vid": version_id},
            )


def test_draft_row_editable_at_db(migrated_database) -> None:
    tenant_id = uuid.uuid4()
    company_id = uuid.uuid4()
    version_id = uuid.uuid4()
    with migrated_database.begin() as connection:
        connection.execute(
            text("INSERT INTO tenants (id, name, created_at) VALUES (:id, 't', now())"),
            {"id": tenant_id},
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
                """
                INSERT INTO organization_profile_versions (
                  id, tenant_id, company_id, effective_from
                ) VALUES (:vid, :t, :c, '2026-01-01')
                """
            ),
            {"vid": version_id, "t": tenant_id, "c": company_id},
        )
        connection.execute(
            text(
                "UPDATE organization_profile_versions SET tax_system = 'usn' WHERE id = :vid"
            ),
            {"vid": version_id},
        )
        tax = connection.execute(
            text("SELECT tax_system FROM organization_profile_versions WHERE id = :vid"),
            {"vid": version_id},
        ).scalar_one()
    assert tax == "usn"


def test_delete_forbidden_at_db(migrated_database) -> None:
    tenant_id = uuid.uuid4()
    company_id = uuid.uuid4()
    version_id = uuid.uuid4()
    with migrated_database.begin() as connection:
        connection.execute(
            text("INSERT INTO tenants (id, name, created_at) VALUES (:id, 't', now())"),
            {"id": tenant_id},
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
                """
                INSERT INTO organization_profile_versions (
                  id, tenant_id, company_id, effective_from
                ) VALUES (:vid, :t, :c, '2026-01-01')
                """
            ),
            {"vid": version_id, "t": tenant_id, "c": company_id},
        )
        with pytest.raises(DBAPIError, match="delete_forbidden"):
            connection.execute(
                text("DELETE FROM organization_profile_versions WHERE id = :vid"),
                {"vid": version_id},
            )
