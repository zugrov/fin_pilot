import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from app.integrations.imap_client import FakeMailbox, MailAttachment
from app.models.identity import Company, Membership, User
from app.models.imports import ImportBatch, SourceConnection
from app.security.context import set_context
from app.services.import_service import upload_file
from app.services.mail_service import ingest_mailbox
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import BACKEND, login, open_workspace, pay, register_and_verify

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"
RECEIVED = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
REVISION = "20261018_0011"
PREV = "20261017_0010"
_PG_PORT = __import__("os").environ.get("TEST_PG_PORT", "5432")


def _rows(admin, query: str, params: dict | None = None) -> list:
    with admin.connect() as connection:
        return list(connection.execute(text(query), params or {}).all())


def _ready(client, admin, app, fake, tmp_path, email: str) -> tuple[str, str]:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Transport")
    company = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Фирма", "kind": "company"},
    )
    assert company.status_code == 200, company.text
    company_id = company.json()["id"]
    pay(client, app, fake, 1, "month")
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    wallet = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Расчётный", "type": "bank", "code": "main"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert wallet.status_code == 200, wallet.text
    return company_id, wallet.json()["id"]


def _source(client, company_id: str, wallet_id: str) -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Банк",
            "type": "file",
            "namespace": "bank-transport",
            "format": "csv",
            "encoding": "utf-8",
            "wallet_id": wallet_id,
        },
    )
    assert created.status_code == 200, created.text
    return created.json()


def _upload(client, company_id: str, connection_id: str, content: bytes, key: str):
    return client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": connection_id},
        files={"upload": ("cash.csv", content, "application/octet-stream")},
        headers={"Idempotency-Key": key},
    )


def _mail_source(client, company_id: str, wallet_id: str) -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Почта",
            "type": "email",
            "namespace": "mail-transport",
            "format": "clientbank",
            "wallet_id": wallet_id,
            "dataset": "cash",
            "mailbox": {
                "host": "imap.example.com",
                "username": "box@example.com",
                "folder": "INBOX",
                "sender": "bank@example.com",
                "password": "secret",
            },
        },
    )
    assert created.status_code == 200, created.text
    return created.json()


def _statement(documents: str) -> bytes:
    return (
        f"1CClientBankExchange\nВерсияФормата=1.03\nДатаКонца=13.10.2026\n{documents}КонецФайла\n"
    ).encode()


def _document(number: str, *, valid: bool) -> str:
    lines = [
        "СекцияДокумент=Платежное поручение",
        f"Номер={number}",
        "Сумма=10.00",
    ]
    if valid:
        lines.append("ДатаПоступило=13.10.2026")
    lines.append("КонецДокумента")
    return "\n".join(lines) + "\n"


def _ingest_mail(app, tenant_id: str, user_id: str, source_id: str, mailbox, at: datetime) -> int:
    session = app.state.session_factory()
    try:
        set_context(session, tenant_id=UUID(tenant_id), user_id=UUID(user_id))
        connection = session.get(SourceConnection, UUID(source_id))
        user = session.get(User, UUID(user_id))
        assert connection is not None and user is not None
        saved = ingest_mailbox(session, app.state.settings, connection, mailbox, user, at)
        session.commit()
        return saved
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def test_ui_same_file_two_deliveries_one_batch(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "td-ui-1@example.com")
    source = _source(client, company_id, wallet_id)
    content = (FIXTURES / "cash_ok.csv").read_bytes()
    first = _upload(client, company_id, source["id"], content, "td-key-a")
    second = _upload(client, company_id, source["id"], content, "td-key-b")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["delivery_id"] != second.json()["delivery_id"]
    assert _rows(admin, "SELECT count(*) FROM ingestion_deliveries")[0][0] == 2
    assert _rows(admin, "SELECT count(*) FROM ingestion_delivery_parts")[0][0] == 2
    assert _rows(admin, "SELECT count(*) FROM import_batches")[0][0] == 1
    batch_delivery = _rows(admin, "SELECT delivery_id::text FROM import_batches")[0][0]
    assert batch_delivery == first.json()["delivery_id"]
    assert batch_delivery != second.json()["delivery_id"]


def test_ui_legacy_batch_keeps_null_delivery_on_duplicate_file(
    client, admin, app, fake, tmp_path
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "td-legacy@example.com")
    source = _source(client, company_id, wallet_id)
    content = (FIXTURES / "cash_ok.csv").read_bytes()
    first = _upload(client, company_id, source["id"], content, "legacy-a")
    assert first.status_code == 200, first.text
    with admin.connect() as connection:
        connection.execute(text("UPDATE import_batches SET delivery_id = NULL"))
        connection.commit()
    second = _upload(client, company_id, source["id"], content, "legacy-b")
    assert second.status_code == 200, second.text
    assert _rows(admin, "SELECT delivery_id FROM import_batches")[0][0] is None
    assert (
        _rows(admin, "SELECT count(*) FROM ingestion_delivery_parts WHERE batch_id IS NOT NULL")[0][
            0
        ]
        == 2
    )


def test_ui_idempotency_replay_and_payload_conflict(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "td-ui-2@example.com")
    source = _source(client, company_id, wallet_id)
    content = (FIXTURES / "cash_ok.csv").read_bytes()
    other = content + b"\n"
    first = _upload(client, company_id, source["id"], content, "td-same")
    replay = _upload(client, company_id, source["id"], content, "td-same")
    clash = _upload(client, company_id, source["id"], other, "td-same")
    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json()["delivery_id"] == first.json()["delivery_id"]
    assert clash.status_code == 409
    assert clash.json()["code"] == "idempotency_conflict"
    assert _rows(admin, "SELECT count(*) FROM ingestion_deliveries")[0][0] == 1


def test_ui_different_users_same_idempotency_key(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "td-ui-3a@example.com")
    source = _source(client, company_id, wallet_id)
    content = (FIXTURES / "cash_ok.csv").read_bytes()
    shared = "shared-ui-key"
    first = _upload(client, company_id, source["id"], content, shared)
    register_and_verify(client, admin, "td-ui-3b@example.com")
    login(client, "td-ui-3b@example.com")
    tenant_b = open_workspace(client, "Transport B")
    company_b = client.post(
        f"/api/v1/workspaces/{tenant_b}/companies",
        json={"name": "Фирма B", "kind": "company"},
    )
    assert company_b.status_code == 200
    company_b_id = company_b.json()["id"]
    pay(client, app, fake, 1, "month")
    client.post(f"/api/v1/billing/companies/{company_b_id}/activate")
    wallet_b = client.post(
        f"/api/v1/companies/{company_b_id}/wallets",
        json={"name": "Расчётный", "type": "bank", "code": "main"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    source_b = client.post(
        f"/api/v1/companies/{company_b_id}/sources",
        json={
            "name": "Банк",
            "type": "file",
            "namespace": "bank-b",
            "format": "csv",
            "encoding": "utf-8",
            "wallet_id": wallet_b.json()["id"],
        },
    )
    second = _upload(client, company_b_id, source_b.json()["id"], content, shared)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["delivery_id"] != second.json()["delivery_id"]


def test_ui_failed_upload_leaves_no_orphan_idempotency(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "td-ui-4@example.com")
    source = _source(client, company_id, wallet_id)
    bad = _upload(client, company_id, source["id"], b"not-a-csv", "td-fail")
    assert bad.status_code == 422
    assert _rows(admin, "SELECT count(*) FROM import_batches")[0][0] == 0
    assert (
        _rows(admin, "SELECT count(*) FROM idempotency_records WHERE scope = 'import-upload'")[0][0]
        == 0
    )
    assert _rows(admin, "SELECT count(*) FROM ingestion_deliveries")[0][0] == 0
    assert _rows(admin, "SELECT count(*) FROM ingestion_delivery_parts")[0][0] == 0


def _run_ui_concurrent_same_file_two_sessions(
    client, admin, app, fake, tmp_path, *, email: str
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, email)
    owner_id = UUID(client.get("/api/v1/auth/me").json()["user"]["id"])
    tenant_id = UUID(client.headers["X-Tenant-Id"])
    source = _source(client, company_id, wallet_id)
    content = (FIXTURES / "cash_ok.csv").read_bytes()
    at = RECEIVED
    marker_name = f"race-marker-{uuid4().hex[:8]}"
    prep = app.state.session_factory()
    try:
        set_context(prep, tenant_id=tenant_id, user_id=owner_id)
        prep.execute(
            text("UPDATE wallets SET name = :name WHERE id = :wallet_id"),
            {"name": marker_name, "wallet_id": wallet_id},
        )
        prep.commit()
    finally:
        prep.close()

    payloads: list[dict] = []
    errors: list[BaseException] = []
    start_barrier = threading.Barrier(2)
    batch_barrier = threading.Barrier(2)
    real_batch_init = ImportBatch.__init__

    def batch_init_with_barrier(self, *args, **kwargs):
        batch_barrier.wait(timeout=5)
        return real_batch_init(self, *args, **kwargs)

    def worker(key: str) -> None:
        start_barrier.wait(timeout=5)
        session = app.state.session_factory()
        try:
            set_context(session, tenant_id=tenant_id, user_id=owner_id)
            user = session.get(User, owner_id)
            company = session.get(Company, UUID(company_id))
            membership = session.scalar(
                select(Membership).where(
                    Membership.user_id == user.id,
                    Membership.tenant_id == company.tenant_id,
                    Membership.role == "owner",
                )
            )
            assert user is not None and company is not None and membership is not None
            body = upload_file(
                session,
                membership,
                company,
                user,
                app.state.settings,
                connection_id=UUID(source["id"]),
                content=content,
                idempotency_key=key,
                at=at,
            )
            session.execute(text("SELECT 1"))
            session.commit()
            payloads.append(body)
        except BaseException as exc:
            session.rollback()
            errors.append(exc)
        finally:
            session.close()

    with patch.object(ImportBatch, "__init__", batch_init_with_barrier):
        threads = [
            threading.Thread(target=worker, args=(f"race-{index}",)) for index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

    assert errors == [], errors
    assert len(payloads) == 2
    batch_id = payloads[0]["id"]
    assert all(item["id"] == batch_id for item in payloads)
    assert len({item["delivery_id"] for item in payloads}) == 2
    assert _rows(admin, "SELECT count(*) FROM import_batches")[0][0] == 1
    assert _rows(admin, "SELECT count(*) FROM ingestion_deliveries")[0][0] == 2
    assert _rows(admin, "SELECT count(*) FROM ingestion_delivery_parts")[0][0] == 2
    part_batches = _rows(admin, "SELECT batch_id::text FROM ingestion_delivery_parts")
    assert len(part_batches) == 2 and all(row[0] == batch_id for row in part_batches)
    assert (
        _rows(admin, "SELECT count(*) FROM idempotency_records WHERE scope = 'import-upload'")[0][0]
        == 2
    )
    assert _rows(admin, "SELECT count(*) FROM raw_import_rows")[0][0] == 2
    assert (
        _rows(
            admin,
            "SELECT count(*) FROM audit_log WHERE action = 'import_received'",
        )[0][0]
        == 1
    )
    transport_rows = _rows(admin, "SELECT transport_status FROM ingestion_deliveries")
    assert transport_rows == [("transport_complete",), ("transport_complete",)]
    assert (
        _rows(
            admin,
            "SELECT name FROM wallets WHERE id = :wallet_id",
            {"wallet_id": wallet_id},
        )[0][0]
        == marker_name
    )


def test_ui_concurrent_same_file_two_sessions(client, admin, app, fake, tmp_path) -> None:
    _run_ui_concurrent_same_file_two_sessions(
        client, admin, app, fake, tmp_path, email="td-race@example.com"
    )


@pytest.mark.parametrize("attempt", range(20))
def test_ui_concurrent_same_file_two_sessions_stability(
    client, admin, app, fake, tmp_path, attempt: int
) -> None:
    _run_ui_concurrent_same_file_two_sessions(
        client,
        admin,
        app,
        fake,
        tmp_path,
        email=f"td-race-stress-{attempt}@example.com",
    )


def test_mail_repeat_preserves_complete_and_preview_parts(
    client, admin, app, fake, tmp_path
) -> None:
    tenant_id, company_id, user_id = _mail_ready(
        client, admin, app, fake, tmp_path, "td-mail-2@example.com"
    )
    source = _mail_source(client, company_id, _wallet(client, company_id))
    content = _statement(_document("r1", valid=True))
    box = FakeMailbox([_letter(content, 20)])
    assert _ingest_mail(app, tenant_id, user_id, source["id"], box, RECEIVED) == 1
    status_after_first = _rows(admin, "SELECT transport_status FROM ingestion_deliveries")[0][0]
    part_after_first = _rows(
        admin,
        "SELECT part_status, batch_id IS NOT NULL FROM ingestion_delivery_parts",
    )[0]
    assert status_after_first == "transport_complete"
    assert part_after_first[0] == "preview"
    assert part_after_first[1] is True
    assert (
        _ingest_mail(app, tenant_id, user_id, source["id"], box, RECEIVED + timedelta(minutes=1))
        == 0
    )
    assert (
        _rows(admin, "SELECT transport_status FROM ingestion_deliveries")[0][0]
        == "transport_complete"
    )
    assert _rows(
        admin,
        "SELECT part_status, batch_id IS NOT NULL FROM ingestion_delivery_parts",
    )[0] == ("preview", True)


def test_mail_partial_failure_stays_partial_on_repeat(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, user_id = _mail_ready(
        client, admin, app, fake, tmp_path, "td-mail-partial@example.com"
    )
    source = _mail_source(client, company_id, _wallet(client, company_id))
    good = _statement(_document("ok", valid=True))
    bad_bytes = b"not-a-statement"
    box = FakeMailbox(
        [_letter(good, 40, filename="a.txt"), _letter(bad_bytes, 40, filename="b.txt")]
    )
    _ingest_mail(app, tenant_id, user_id, source["id"], box, RECEIVED)
    statuses = sorted(
        row[0]
        for row in _rows(
            admin, "SELECT part_status FROM ingestion_delivery_parts ORDER BY part_index"
        )
    )
    delivery_status = _rows(admin, "SELECT transport_status FROM ingestion_deliveries")[0][0]
    assert "preview" in statuses
    assert "failed" in statuses
    assert delivery_status == "partially_received"
    _ingest_mail(app, tenant_id, user_id, source["id"], box, RECEIVED + timedelta(minutes=1))
    assert (
        _rows(admin, "SELECT transport_status FROM ingestion_deliveries")[0][0]
        == "partially_received"
    )
    assert (
        sorted(
            row[0]
            for row in _rows(
                admin, "SELECT part_status FROM ingestion_delivery_parts ORDER BY part_index"
            )
        )
        == statuses
    )


def test_mail_duplicate_attachment_one_batch(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, user_id = _mail_ready(
        client, admin, app, fake, tmp_path, "td-mail-3@example.com"
    )
    source = _mail_source(client, company_id, _wallet(client, company_id))
    content = _statement(_document("dup", valid=True))
    attachments = [
        _letter(content, 30, filename="a.txt"),
        _letter(content, 30, filename="b.txt"),
    ]
    assert (
        _ingest_mail(app, tenant_id, user_id, source["id"], FakeMailbox(attachments), RECEIVED) == 1
    )
    assert _rows(admin, "SELECT count(*) FROM import_batches")[0][0] == 1
    batch_ids = _rows(
        admin, "SELECT batch_id::text FROM ingestion_delivery_parts ORDER BY part_index"
    )
    assert batch_ids[0][0] == batch_ids[1][0]
    assert batch_ids[0][0] is not None
    assert (
        _rows(admin, "SELECT transport_status FROM ingestion_deliveries")[0][0]
        == "transport_complete"
    )


def test_mail_one_delivery_many_parts(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, user_id = _mail_ready(
        client, admin, app, fake, tmp_path, "td-mail-1@example.com"
    )
    source = _mail_source(client, company_id, _wallet(client, company_id))
    good = _statement(_document("m1", valid=True))
    bad = _statement(_document("m2", valid=False))
    box = FakeMailbox([_letter(good, 10, filename="a.txt"), _letter(bad, 10, filename="b.txt")])
    assert _ingest_mail(app, tenant_id, user_id, source["id"], box, RECEIVED) == 1
    assert _rows(admin, "SELECT count(*) FROM ingestion_deliveries")[0][0] == 1
    assert _rows(admin, "SELECT count(*) FROM ingestion_delivery_parts")[0][0] == 2
    assert _rows(admin, "SELECT count(DISTINCT batch_id) FROM ingestion_delivery_parts")[0][0] == 2
    assert (
        _rows(admin, "SELECT transport_status FROM ingestion_deliveries")[0][0]
        == "transport_complete"
    )


def test_cross_connection_part_fk_rejected(admin, migrated_database) -> None:
    assert_finpilot_test_database(migrated_database)
    with migrated_database.connect() as connection:
        sources = connection.execute(
            text(
                "SELECT tenant_id, company_id, id FROM source_connections "
                "ORDER BY created_at LIMIT 2"
            )
        ).all()
    if len(sources) < 2:
        pytest.skip("нужно два source_connection")
    a, b = sources[0], sources[1]
    delivery_id = uuid.uuid4()
    with pytest.raises(IntegrityError):
        with migrated_database.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ingestion_deliveries "
                    "(id, tenant_id, company_id, connection_id, channel, delivery_key, "
                    "request_fingerprint, transport_status, created_at, updated_at) "
                    "VALUES (:id, :t, :c, :conn, 'ui', 'fk-test', 'fp', "
                    "'partially_received', now(), now())"
                ),
                {"id": delivery_id, "t": a.tenant_id, "c": a.company_id, "conn": b.id},
            )


def test_rls_hides_foreign_tenant_delivery(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "td-rls@example.com")
    source = _source(client, company_id, wallet_id)
    content = (FIXTURES / "cash_ok.csv").read_bytes()
    uploaded = _upload(client, company_id, source["id"], content, "rls-key")
    assert uploaded.status_code == 200, uploaded.text
    delivery_id = uploaded.json()["delivery_id"]
    app_conn = psycopg.connect(
        f"postgresql://finpilot_app:finpilot_test_only@127.0.0.1:{_PG_PORT}/finpilot_test"
    )
    try:
        with app_conn.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('app.tenant_id', %s, true)",
                ("00000000-0000-0000-0000-000000000001",),
            )
            cursor.execute(
                "SELECT count(*) FROM ingestion_deliveries WHERE id = %s",
                (delivery_id,),
            )
            assert cursor.fetchone()[0] == 0
    finally:
        app_conn.close()


def test_migration_downgrade_blocked_with_transport_history(
    client, admin, app, fake, tmp_path, migrated_database
) -> None:
    assert_finpilot_test_database(migrated_database)
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "td-down@example.com")
    source = _source(client, company_id, wallet_id)
    content = (FIXTURES / "cash_ok.csv").read_bytes()
    uploaded = _upload(client, company_id, source["id"], content, "down-key")
    assert uploaded.status_code == 200, uploaded.text
    assert _rows(admin, "SELECT count(*) FROM ingestion_deliveries")[0][0] >= 1
    config = Config(str(BACKEND / "alembic.ini"))
    with pytest.raises(Exception) as exc:
        command.downgrade(config, PREV)
    assert "downgrade_blocked" in str(exc.value)
    with migrated_database.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        deliveries = connection.execute(
            text("SELECT count(*) FROM ingestion_deliveries")
        ).scalar_one()
    assert revision == REVISION
    assert int(deliveries) >= 1


def test_migration_sql_downgrade_guard(migrated_database) -> None:
    assert_finpilot_test_database(migrated_database)
    downgrade_sql = (
        BACKEND / "alembic" / "sql" / "0011_ingestion_delivery_downgrade.sql"
    ).read_text(encoding="utf-8")
    assert "downgrade_blocked" in downgrade_sql
    with migrated_database.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert revision == REVISION


def _wallet(client, company_id: str) -> str:
    listed = client.get(f"/api/v1/companies/{company_id}/wallets")
    assert listed.status_code == 200, listed.text
    return listed.json()["wallets"][0]["id"]


def _mail_ready(client, admin, app, fake, tmp_path, email: str) -> tuple[str, str, str]:
    app.state.settings.import_storage_dir = str(tmp_path)
    app.state.settings.poll_imap = False
    register_and_verify(client, admin, email)
    logged = login(client, email)
    tenant_id = open_workspace(client, "Mail transport")
    company = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Фирма", "kind": "company"},
    )
    assert company.status_code == 200, company.text
    company_id = company.json()["id"]
    pay(client, app, fake, 1, "month")
    client.post(f"/api/v1/billing/companies/{company_id}/activate")
    client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Расчётный", "type": "bank", "code": "main"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    return tenant_id, company_id, logged["user"]["id"]


def _letter(
    content: bytes, uid: int, uidvalidity: int = 4, filename: str = "stmt.txt"
) -> MailAttachment:
    return MailAttachment(
        uidvalidity=uidvalidity,
        uid=uid,
        message_id=f"<{uid}@bank>",
        sender="bank@example.com",
        folder="INBOX",
        filename=filename,
        content=content,
    )
