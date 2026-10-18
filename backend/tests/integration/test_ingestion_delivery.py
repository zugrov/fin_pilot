from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from app.integrations.imap_client import FakeMailbox, MailAttachment
from app.models.identity import User
from app.models.imports import SourceConnection
from app.security.context import set_context
from app.services.mail_service import ingest_mailbox
from sqlalchemy import text
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import BACKEND, login, open_workspace, pay, register_and_verify

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"
RECEIVED = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
REVISION = "20261018_0011"


def _rows(admin, query: str) -> list:
    with admin.connect() as connection:
        return list(connection.execute(text(query)).all())


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
    assert _rows(admin, "SELECT delivery_id IS NOT NULL FROM import_batches")[0][0] is True


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
    status = _rows(admin, "SELECT transport_status FROM ingestion_deliveries")[0][0]
    assert status == "transport_complete"


def test_mail_repeat_and_uidvalidity(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, user_id = _mail_ready(
        client, admin, app, fake, tmp_path, "td-mail-2@example.com"
    )
    source = _mail_source(client, company_id, _wallet(client, company_id))
    content = _statement(_document("r1", valid=True))
    box = FakeMailbox([_letter(content, 20)])
    assert _ingest_mail(app, tenant_id, user_id, source["id"], box, RECEIVED) == 1
    assert (
        _ingest_mail(app, tenant_id, user_id, source["id"], box, RECEIVED + timedelta(minutes=1))
        == 0
    )
    assert (
        _rows(admin, "SELECT transport_status FROM ingestion_deliveries")[0][0]
        == "duplicate_transport"
    )
    new_box = FakeMailbox([_letter(content, 20, uidvalidity=99)])
    assert _ingest_mail(app, tenant_id, user_id, source["id"], new_box, RECEIVED) == 1
    assert _rows(admin, "SELECT count(*) FROM ingestion_deliveries")[0][0] == 2


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
    assert _rows(admin, "SELECT count(*) FROM ingestion_delivery_parts")[0][0] == 2


def test_migration_sql_downgrade_guard(migrated_database) -> None:
    assert_finpilot_test_database(migrated_database)
    upgrade_sql = (BACKEND / "alembic" / "sql" / "0011_ingestion_delivery.sql").read_text(
        encoding="utf-8"
    )
    assert "ingestion_deliveries" in upgrade_sql
    assert "ROW LEVEL SECURITY" in upgrade_sql
    downgrade_sql = (
        BACKEND / "alembic" / "sql" / "0011_ingestion_delivery_downgrade.sql"
    ).read_text(encoding="utf-8")
    assert "downgrade_blocked" in downgrade_sql
    assert downgrade_sql.index("downgrade_blocked") < downgrade_sql.index("DROP TABLE")
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
