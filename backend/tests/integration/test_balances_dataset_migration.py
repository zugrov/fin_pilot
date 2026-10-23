import os
import threading
import time
import uuid

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import BACKEND
from tests.integration.test_balances_import import _balances_source, _ready

HEAD = "20261022_0016"
REVISION = "20261017_0010"
PREV = "20261014_0009"


@pytest.fixture(autouse=True)
def _guard_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


def _alembic_config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    return config


def _current_revision(engine) -> str | None:
    with engine.connect() as connection:
        try:
            return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        except Exception:
            return None


def _constraint_allows(engine, dataset: str) -> bool:
    tenant_id = uuid.uuid4()
    company_id = uuid.uuid4()
    source_id = uuid.uuid4()
    user_id = uuid.uuid4()
    with engine.begin() as connection:
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
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at) "
                "VALUES (:id, :t, :u, 'owner', now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "u": user_id},
        )
        now_sql = "now()"
        connection.execute(
            text(
                "INSERT INTO companies "
                "(id, tenant_id, name, kind, timezone, created_at, updated_at) "
                f"VALUES (:id, :t, 'c', 'company', 'Europe/Moscow', {now_sql}, {now_sql})"
            ),
            {"id": company_id, "t": tenant_id},
        )
        try:
            connection.execute(
                text(
                    "INSERT INTO source_connections "
                    "(id, tenant_id, company_id, type, name, namespace, format, encoding, "
                    "dataset, vat_basis, created_at, status) "
                    "VALUES (:id, :t, :c, 'file', 'n', :ns, 'csv', 'utf-8', "
                    ":ds, 'net', now(), 'active')"
                ),
                {
                    "id": source_id,
                    "t": tenant_id,
                    "c": company_id,
                    "ds": dataset,
                    "ns": f"m-{uuid.uuid4().hex[:8]}",
                },
            )
            return True
        except Exception:
            return False


def _migration_dsn() -> str:
    port = os.environ.get("TEST_PG_PORT", "5432")
    return f"postgresql://127.0.0.1:{port}/finpilot_test"


def _constraint_definition(engine) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'source_connections'::regclass "
                    "AND conname = 'source_connections_dataset_ck'"
                )
            ).scalar_one()
        )


def _error_chain(exc: BaseException) -> list[BaseException]:
    seen: set[int] = set()
    chain: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return chain


def _lock_timeout_from_upgrade(exc: BaseException) -> tuple[bool, str | None]:
    for item in _error_chain(exc):
        sqlstate = getattr(item, "sqlstate", None)
        if sqlstate == "55P03":
            return True, sqlstate
        message = str(item).lower()
        if "lock timeout" in message:
            return True, sqlstate
    return False, None


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


def test_dataset_ck_allows_legacy_four(migrated_database, restore_head) -> None:
    for dataset in ("cash", "revenue", "plan", "budget"):
        assert _constraint_allows(migrated_database, dataset), dataset


def test_dataset_ck_allows_balances(migrated_database, restore_head) -> None:
    assert _constraint_allows(migrated_database, "balances")


def test_dataset_ck_rejects_unknown(migrated_database, restore_head) -> None:
    assert not _constraint_allows(migrated_database, "ledger")


def test_downgrade_without_balances_rows(migrated_database, restore_head) -> None:
    _run_alembic("downgrade", PREV)
    try:
        assert _current_revision(migrated_database) == PREV
        assert not _constraint_allows(migrated_database, "balances")
        for dataset in ("cash", "revenue", "plan", "budget"):
            assert _constraint_allows(migrated_database, dataset), dataset
    finally:
        _run_alembic("upgrade", "head")


def test_downgrade_blocked_when_balances_source_exists(
    client, admin, app, fake, tmp_path, migrated_database, restore_head
) -> None:
    app.state.settings.balances_import_enabled = True
    company_id, _ = _ready(client, admin, app, fake, tmp_path, "mig-bal@example.com")
    _balances_source(client, company_id)
    with pytest.raises(Exception) as exc:
        _run_alembic("downgrade", PREV)
    assert "downgrade_blocked" in str(exc.value)
    assert _current_revision(migrated_database) == HEAD
    assert _constraint_allows(migrated_database, "balances")
    with admin.connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM source_connections WHERE dataset = 'balances'")
        ).scalar_one()
    assert int(count) >= 1


def test_migration_upgrade_lock_timeout_live(migrated_database, restore_head) -> None:
    """Live: upgrade 0010 при удержанной ACCESS EXCLUSIVE на source_connections → lock timeout."""
    assert_finpilot_test_database(migrated_database)

    _run_alembic("downgrade", PREV)
    assert _current_revision(migrated_database) == PREV
    assert not _constraint_allows(migrated_database, "balances")

    conn_a = psycopg.connect(_migration_dsn(), autocommit=False)
    upgrade_outcome: dict[str, object] = {"exc": None, "elapsed": 0.0}

    def _upgrade_in_thread() -> None:
        started = time.monotonic()
        try:
            _run_alembic("upgrade", REVISION)
        except Exception as exc:
            upgrade_outcome["exc"] = exc
        finally:
            upgrade_outcome["elapsed"] = time.monotonic() - started

    try:
        with conn_a.cursor() as cursor:
            cursor.execute("LOCK TABLE source_connections IN ACCESS EXCLUSIVE MODE")

        worker = threading.Thread(target=_upgrade_in_thread, name="alembic-upgrade-0010")
        worker.start()
        worker.join(timeout=90.0)
        assert not worker.is_alive(), "upgrade не завершился за 90s"

        exc = upgrade_outcome["exc"]
        assert exc is not None, "upgrade должен упасть из-за lock timeout"
        is_lock_timeout, sqlstate = _lock_timeout_from_upgrade(exc)
        assert is_lock_timeout, f"ожидали lock timeout, получили: {exc!r}"
        assert sqlstate == "55P03" or sqlstate is None

        elapsed = float(upgrade_outcome["elapsed"])
        assert 3.0 <= elapsed <= 20.0, f"ожидали ~5s lock_timeout, elapsed={elapsed:.2f}s"
        messages = " ".join(str(item).lower() for item in _error_chain(exc))
        assert "lock timeout" in messages
        assert "due to statement timeout" not in messages

        assert _current_revision(migrated_database) == PREV

    finally:
        try:
            conn_a.rollback()
        finally:
            conn_a.close()

    assert not _constraint_allows(migrated_database, "balances")
    definition = _constraint_definition(migrated_database)
    assert "balances" not in definition
    assert "'budget'" in definition

    _run_alembic("upgrade", "head")
    assert _current_revision(migrated_database) == HEAD
    assert _constraint_allows(migrated_database, "balances")
    assert "balances" in _constraint_definition(migrated_database)


def test_migration_sql_timeouts_lock_and_downgrade_guard(migrated_database, restore_head) -> None:
    """DDL в одной revision Alembic; LOCK/таймауты и guard до DROP зафиксированы в SQL."""
    upgrade_sql = (BACKEND / "alembic" / "sql" / "0010_balances_dataset.sql").read_text(
        encoding="utf-8"
    )
    assert "lock_timeout = '5s'" in upgrade_sql
    assert "statement_timeout = '60s'" in upgrade_sql
    assert "LOCK TABLE source_connections IN ACCESS EXCLUSIVE MODE" in upgrade_sql
    assert upgrade_sql.index("DROP CONSTRAINT") < upgrade_sql.index("ADD CONSTRAINT")
    downgrade_sql = (BACKEND / "alembic" / "sql" / "0010_balances_dataset_downgrade.sql").read_text(
        encoding="utf-8"
    )
    assert "downgrade_blocked" in downgrade_sql
    assert downgrade_sql.index("downgrade_blocked") < downgrade_sql.index("DROP CONSTRAINT")
    assert _current_revision(migrated_database) == HEAD
