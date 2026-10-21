import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.domain.mail_ingress import MailIngressStage, build_simple_mime
from app.errors import AppError
from app.services.mail_quarantine_service import expire_mail_quarantine_entries
from sqlalchemy import create_engine, text
from tests.integration.conftest import BACKEND, HEAD_REVISION, freeze
from tests.integration.test_mail_ingress import (
    _bundle,
    _counts,
    _document,
    _ingest,
    _ready,
    _statement,
)

PREV_REVISION = "20261019_0014"
_PORT = os.environ.get("TEST_PG_PORT", "5432")


def _enable_quarantine(app, *, daily_limit: int = 200) -> None:
    app.state.settings.mail_quarantine_enabled = True
    app.state.settings.mail_quarantine_daily_entry_limit = daily_limit


def _quarantine_counts(admin) -> dict[str, int]:
    tables = (
        "mail_quarantine_entries",
        "mail_quarantine_daily_stats",
        "mail_quarantine_miss_metrics",
    )
    with admin.connect() as connection:
        return {
            name: int(connection.execute(text(f"SELECT count(*) FROM {name}")).scalar_one())
            for name in tables
        }


def _entries(admin, where: str = "") -> list[tuple]:
    clause = f" WHERE {where}" if where else ""
    with admin.connect() as connection:
        return connection.execute(
            text(
                "SELECT message_digest, slot_content_anomaly, status, reason_code, "
                f"metadata_allowed FROM mail_quarantine_entries{clause} "
                "ORDER BY created_at, message_digest"
            )
        ).fetchall()


def _alembic_downgrade(target: str) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    previous = os.getcwd()
    os.chdir(BACKEND)
    try:
        command.downgrade(config, target)
    finally:
        os.chdir(previous)


@pytest.fixture
def restore_head(migrated_database):
    yield
    config = Config(str(BACKEND / "alembic.ini"))
    previous = os.getcwd()
    os.chdir(BACKEND)
    try:
        command.upgrade(config, "head")
    finally:
        os.chdir(previous)


def test_reject_writes_quarantine_when_enabled(client, admin, app, fake, tmp_path) -> None:
    email = "q-reject@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app)
    raw = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"x",
    )
    before = _quarantine_counts(admin)
    side_before = _counts(admin)
    result = _ingest(app, raw, _bundle(tenant_id, company_id, user_id, source_id, raw, uid=101))
    after = _quarantine_counts(admin)
    assert result.stage == MailIngressStage.REJECTED
    assert after["mail_quarantine_entries"] == before["mail_quarantine_entries"] + 1
    assert _counts(admin) == side_before
    row = _entries(admin)[0]
    assert row[3] == "sender_not_verified_user"
    assert row[4]["reason_code"] == "sender_not_verified_user"
    assert "subject" not in row[4]


def test_reject_skips_quarantine_when_disabled(client, admin, app, fake, tmp_path) -> None:
    email = "q-off@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    app.state.settings.mail_quarantine_enabled = False
    raw = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"x",
    )
    before = _quarantine_counts(admin)
    _ingest(app, raw, _bundle(tenant_id, company_id, user_id, source_id, raw, uid=102))
    assert _quarantine_counts(admin) == before


def test_same_digest_is_idempotent(client, admin, app, fake, tmp_path) -> None:
    email = "q-idem@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app)
    raw = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"x",
    )
    bundle = _bundle(tenant_id, company_id, user_id, source_id, raw, uid=103)
    _ingest(app, raw, bundle)
    _ingest(app, raw, bundle)
    assert _quarantine_counts(admin)["mail_quarantine_entries"] == 1


def test_two_digests_same_slot_mark_anomaly(client, admin, app, fake, tmp_path) -> None:
    email = "q-anom2@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app)
    raw1 = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="a.txt",
        attachment_bytes=b"one",
    )
    raw2 = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="b.txt",
        attachment_bytes=b"two",
    )
    slot = _bundle(tenant_id, company_id, user_id, source_id, raw1, uid=104)
    _ingest(app, raw1, slot)
    slot2 = _bundle(tenant_id, company_id, user_id, source_id, raw2, uid=104)
    _ingest(app, raw2, slot2)
    rows = _entries(admin)
    assert len(rows) == 2
    assert all(row[1] is True for row in rows)


def test_three_digests_same_slot(client, admin, app, fake, tmp_path) -> None:
    email = "q-anom3@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app)
    for idx, body in enumerate((b"1", b"2", b"3")):
        raw = build_simple_mime(
            from_addr="wrong@example.com",
            attachment_name=f"f{idx}.txt",
            attachment_bytes=body,
        )
        _ingest(
            app,
            raw,
            _bundle(tenant_id, company_id, user_id, source_id, raw, uid=105),
        )
    assert len(_entries(admin)) == 3
    assert all(row[1] is True for row in _entries(admin))


def test_same_message_id_different_slots(client, admin, app, fake, tmp_path) -> None:
    email = "q-mid@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app)
    content = _statement("13.10.2026", _document("q-1", "13.10.2026"))
    for uid in (106, 107):
        raw = build_simple_mime(
            from_addr="wrong@example.com",
            attachment_name="stmt.txt",
            attachment_bytes=content,
            message_id="<shared-mid@bank>",
        )
        _ingest(app, raw, _bundle(tenant_id, company_id, user_id, source_id, raw, uid=uid))
    assert _quarantine_counts(admin)["mail_quarantine_entries"] == 2


def test_concurrent_same_key_single_row(client, admin, app, fake, tmp_path) -> None:
    email = "q-race@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app)
    raw = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"race",
    )
    bundle = _bundle(tenant_id, company_id, user_id, source_id, raw, uid=108)

    def _run() -> None:
        _ingest(app, raw, bundle)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: _run(), range(2)))
    assert _quarantine_counts(admin)["mail_quarantine_entries"] == 1


def test_daily_limit_overflow_counter(client, admin, app, fake, tmp_path) -> None:
    email = "q-limit@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app, daily_limit=2)
    for idx in range(3):
        raw = build_simple_mime(
            from_addr="wrong@example.com",
            attachment_name=f"l{idx}.txt",
            attachment_bytes=f"body-{idx}".encode(),
        )
        _ingest(
            app,
            raw,
            _bundle(tenant_id, company_id, user_id, source_id, raw, uid=109),
        )
    assert _quarantine_counts(admin)["mail_quarantine_entries"] == 2
    with admin.connect() as connection:
        overflow = connection.execute(
            text("SELECT overflow_count FROM mail_quarantine_daily_stats")
        ).scalar_one()
    assert int(overflow) == 1


def test_mail_quarantine_policies_target_roles(admin) -> None:
    with admin.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT tablename, policyname, roles::text
                FROM pg_policies
                WHERE tablename LIKE 'mail_quarantine_%'
                ORDER BY tablename, policyname
                """
            )
        ).fetchall()
    assert rows
    for _table, _name, roles in rows:
        assert "finpilot_app" in roles or "finpilot_worker" in roles
    worker_retention = [
        row
        for row in rows
        if row[0] == "mail_quarantine_entries"
        and "worker" in row[1]
        and ("select" in row[1] or "update" in row[1])
    ]
    assert len(worker_retention) >= 2
    app_with_retention = [
        row
        for row in rows
        if row[0] == "mail_quarantine_entries"
        and "app" in row[1]
        and "retention" in row[1].lower()
    ]
    assert app_with_retention == []


def test_app_retention_flag_does_not_leak_other_tenant(
    client, admin, app, fake, tmp_path
) -> None:
    email = "q-ret-rls@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app)
    raw = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"x",
    )
    _ingest(app, raw, _bundle(tenant_id, company_id, user_id, source_id, raw, uid=116))
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as connection:
        connection.execute(
            text("SELECT set_config('app.mail_quarantine_retention', '1', true)")
        )
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(uuid4())},
        )
        visible = connection.execute(
            text("SELECT count(*) FROM mail_quarantine_entries")
        ).scalar_one()
    assert int(visible) == 0


def test_delete_forbidden_for_app_and_worker(client, admin, app, fake, tmp_path) -> None:
    email = "q-del@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app)
    raw = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"x",
    )
    _ingest(app, raw, _bundle(tenant_id, company_id, user_id, source_id, raw, uid=117))
    for url in (os.environ["DATABASE_URL"], os.environ["WORKER_DATABASE_URL"]):
        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": tenant_id},
            )
            with pytest.raises(Exception) as exc:
                connection.execute(
                    text("DELETE FROM mail_quarantine_entries WHERE tenant_id = :tid"),
                    {"tid": tenant_id},
                )
            assert "permission denied" in str(exc.value).lower()


def test_rls_other_tenant_sees_zero(client, admin, app, fake, tmp_path) -> None:
    email = "q-rls@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app)
    raw = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"x",
    )
    _ingest(app, raw, _bundle(tenant_id, company_id, user_id, source_id, raw, uid=110))
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(uuid4())},
        )
        visible = connection.execute(
            text("SELECT count(*) FROM mail_quarantine_entries")
        ).scalar_one()
    assert int(visible) == 0


def test_direct_update_forbidden(client, admin, app, fake, tmp_path) -> None:
    email = "q-upd@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app)
    raw = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"x",
    )
    _ingest(app, raw, _bundle(tenant_id, company_id, user_id, source_id, raw, uid=111))
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": tenant_id},
        )
        with pytest.raises(Exception) as exc:
            connection.execute(
                text(
                    "UPDATE mail_quarantine_entries SET reason_code = 'hacked' "
                    "WHERE tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
    assert "mail_quarantine" in str(exc.value)


def test_worker_role_has_no_bypassrls(admin) -> None:
    with admin.connect() as connection:
        row = connection.execute(
            text(
                "SELECT rolbypassrls FROM pg_roles "
                "WHERE rolname IN ('finpilot_app', 'finpilot_worker')"
            )
        ).fetchall()
    assert row == [(False,), (False,)]


def test_retention_clears_metadata_only(client, admin, app, fake, tmp_path) -> None:
    email = "q-ret@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app)
    freeze(app, datetime(2010, 1, 1, tzinfo=UTC))
    raw = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"x",
    )
    _ingest(app, raw, _bundle(tenant_id, company_id, user_id, source_id, raw, uid=112))
    before = datetime(2026, 10, 21, tzinfo=UTC)
    worker_engine = create_engine(os.environ["WORKER_DATABASE_URL"])
    from sqlalchemy.orm import sessionmaker

    worker_session = sessionmaker(bind=worker_engine)()
    try:
        changed = expire_mail_quarantine_entries(worker_session, before=before, limit=10)
        worker_session.commit()
    finally:
        worker_session.close()
    assert changed == 1
    row = _entries(admin, f"tenant_id = '{tenant_id}'")[0]
    assert row[2] == "expired"
    assert row[3] == "sender_not_verified_user"
    assert row[4] == {}


def test_missing_source_increments_miss_metric(client, admin, app, fake, tmp_path) -> None:
    email = "q-miss@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app)
    raw = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"x",
    )
    fake_source = str(uuid4())
    _ingest(
        app,
        raw,
        _bundle(tenant_id, company_id, user_id, fake_source, raw, uid=113),
    )
    assert _quarantine_counts(admin)["mail_quarantine_entries"] == 0
    assert _quarantine_counts(admin)["mail_quarantine_miss_metrics"] == 1


def test_quarantine_write_failure_is_controlled(
    client, admin, app, fake, tmp_path, monkeypatch
) -> None:
    email = "q-fail@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app)
    raw = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"x",
    )

    def _fail_record(*args, **kwargs):
        raise AppError(500, "mail_quarantine_write_failed", "fail")

    monkeypatch.setattr(
        "app.services.mail_ingress_service.record_mail_quarantine_for_ingress",
        _fail_record,
    )
    session = app.state.session_factory()
    try:
        with pytest.raises(AppError) as exc:
            from app.services.mail_ingress_service import ingest_trusted_local_mail

            ingest_trusted_local_mail(
                session,
                app.state.settings,
                raw_message=raw,
                bundle=_bundle(tenant_id, company_id, user_id, source_id, raw, uid=114),
                at=app.state.clock.now(),
            )
        assert exc.value.code == "mail_quarantine_write_failed"
    finally:
        session.close()
    assert _quarantine_counts(admin)["mail_quarantine_entries"] == 0


def test_upgrade_0015_on_nonempty_database(
    client, admin, app, fake, tmp_path, migrated_database, restore_head
) -> None:
    email = "q-upg@example.com"
    _ready(client, admin, app, fake, tmp_path, email)
    with migrated_database.connect() as connection:
        companies_before = connection.execute(text("SELECT count(*) FROM companies")).scalar_one()
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert int(companies_before) >= 1
    assert revision == HEAD_REVISION
    _alembic_downgrade(PREV_REVISION)
    with migrated_database.connect() as connection:
        at_0014 = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        companies_mid = connection.execute(text("SELECT count(*) FROM companies")).scalar_one()
    assert at_0014 == PREV_REVISION
    assert int(companies_mid) >= 1
    config = Config(str(BACKEND / "alembic.ini"))
    previous = os.getcwd()
    os.chdir(BACKEND)
    try:
        command.upgrade(config, HEAD_REVISION)
    finally:
        os.chdir(previous)
    app_engine = create_engine(os.environ["DATABASE_URL"])
    with app_engine.connect() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(uuid4())},
        )
        tables = connection.execute(
            text(
                "SELECT to_regclass('mail_quarantine_entries') IS NOT NULL, "
                "has_table_privilege('finpilot_app', 'mail_quarantine_entries', 'SELECT')"
            )
        ).one()
    assert tables[0] is True
    assert tables[1] is True
    with migrated_database.connect() as connection:
        revision_after = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert revision_after == HEAD_REVISION


def test_runtime_downgrade_blocked_with_open_review(
    client, admin, app, fake, tmp_path, migrated_database, restore_head
) -> None:
    email = "q-down@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    _enable_quarantine(app)
    raw = (
        b"From: A <a@example.com>, B <b@example.com>\r\n"
        b"Message-ID: <ambiguous@local>\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"ambiguous\r\n"
    )
    result = _ingest(
        app,
        raw,
        _bundle(tenant_id, company_id, user_id, source_id, raw, uid=115),
    )
    assert result.stage == MailIngressStage.REVIEW
    with migrated_database.connect() as connection:
        revision_before = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert revision_before == HEAD_REVISION
    with pytest.raises(Exception) as exc:
        _alembic_downgrade(PREV_REVISION)
    assert "downgrade_blocked" in str(exc.value)
    with migrated_database.connect() as connection:
        revision_after = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert revision_after == HEAD_REVISION
