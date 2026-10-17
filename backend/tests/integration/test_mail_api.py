from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.integrations.imap_client import FakeMailbox, MailAttachment
from app.models.identity import User
from app.models.imports import SourceConnection
from app.security.context import set_context
from app.services.mail_service import ingest_mailbox
from app.services.telegram_bot import ingest_update
from app.services.telegram_digest import schedule_digests
from sqlalchemy import text
from tests.integration.conftest import (
    freeze,
    login,
    open_workspace,
    pay,
    register_and_verify,
)

RECEIVED = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
SLOT = datetime(2026, 10, 14, 5, 30, tzinfo=UTC)
SECRET = "mailbox-secret-1"


def _ready(client, admin, app, fake, tmp_path, email: str) -> tuple[str, str, str]:
    app.state.settings.import_storage_dir = str(tmp_path)
    app.state.settings.poll_imap = False
    register_and_verify(client, admin, email)
    logged = login(client, email)
    tenant_id = open_workspace(client, "Почта")
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
    return tenant_id, company_id, logged["user"]["id"]


def _mailbox(client, company_id: str, wallet_id: str) -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Выписка",
            "type": "email",
            "namespace": "mail-bank",
            "format": "clientbank",
            "wallet_id": wallet_id,
            "dataset": "cash",
            "mailbox": {
                "host": "imap.example.com",
                "username": "box@example.com",
                "folder": "INBOX",
                "sender": "bank@example.com",
                "password": SECRET,
            },
        },
    )
    assert created.status_code == 200, created.text
    body = created.text
    assert SECRET not in body
    assert "encrypted_credentials" not in created.json()
    return created.json()


def _statement(end: str, documents: str = "") -> bytes:
    return (
        f"1CClientBankExchange\nВерсияФормата=1.03\nДатаКонца={end}\n{documents}КонецФайла\n"
    ).encode()


def _document(number: str, day: str, *, valid: bool) -> str:
    lines = [
        "СекцияДокумент=Платежное поручение",
        f"Номер={number}",
        "Сумма=10.00",
    ]
    if valid:
        lines.append(f"ДатаПоступило={day}")
    lines.append("КонецДокумента")
    return "\n".join(lines) + "\n"


def _letter(content: bytes, uid: int, sender: str = "bank@example.com") -> MailAttachment:
    return MailAttachment(
        uidvalidity=4,
        uid=uid,
        message_id=f"<{uid}@bank>",
        sender=sender,
        folder="INBOX",
        filename="stmt.txt",
        content=content,
    )


def _ingest(app, tenant_id: str, user_id: str, source_id: str, mailbox, at: datetime) -> int:
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


def _rows(admin, query: str) -> list:
    with admin.connect() as connection:
        return list(connection.execute(text(query)).all())


def _wallet(client, company_id: str) -> str:
    listed = client.get(f"/api/v1/companies/{company_id}/wallets")
    assert listed.status_code == 200, listed.text
    return listed.json()["wallets"][0]["id"]


def test_i6_coverage_stays_on_statement_end(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, user_id = _ready(client, admin, app, fake, tmp_path, "i6@example.com")
    wallet_id = _wallet(client, company_id)
    source = _mailbox(client, company_id, wallet_id)
    content = _statement("13.10.2026", _document("ok-1", "13.10.2026", valid=True))
    saved = _ingest(
        app, tenant_id, user_id, source["id"], FakeMailbox([_letter(content, 1)]), RECEIVED
    )
    assert saved == 1
    batch_id = _rows(admin, "SELECT batch_id FROM email_ingestions")[0][0]
    committed = client.post(f"/api/v1/imports/{batch_id}/commit")
    assert committed.status_code == 200, committed.text
    covered = _rows(admin, "SELECT coverage_through::text FROM source_connections")[0][0]
    assert covered == "2026-10-13"
    assert covered != RECEIVED.date().isoformat()
    success = _rows(admin, "SELECT last_success_at IS NOT NULL FROM source_connections")[0][0]
    assert success is True


def test_i7_restart_does_not_repeat_import(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, user_id = _ready(client, admin, app, fake, tmp_path, "i7@example.com")
    wallet_id = _wallet(client, company_id)
    source = _mailbox(client, company_id, wallet_id)
    content = _statement("13.10.2026", _document("ok-1", "13.10.2026", valid=True))
    box = FakeMailbox([_letter(content, 7)])
    assert _ingest(app, tenant_id, user_id, source["id"], box, RECEIVED) == 1
    assert _ingest(app, tenant_id, user_id, source["id"], box, RECEIVED + timedelta(minutes=5)) == 0
    assert _rows(admin, "SELECT count(*) FROM import_batches")[0][0] == 1
    assert _rows(admin, "SELECT count(*) FROM email_ingestions")[0][0] == 1


def test_i8_partial_import_keeps_error_report(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, user_id = _ready(client, admin, app, fake, tmp_path, "i8@example.com")
    wallet_id = _wallet(client, company_id)
    source = _mailbox(client, company_id, wallet_id)
    documents = _document("ok-1", "13.10.2026", valid=True) + _document("bad-1", "", valid=False)
    content = _statement("13.10.2026", documents)
    _ingest(app, tenant_id, user_id, source["id"], FakeMailbox([_letter(content, 8)]), RECEIVED)
    batch_id = _rows(admin, "SELECT batch_id FROM email_ingestions")[0][0]
    committed = client.post(f"/api/v1/imports/{batch_id}/commit")
    assert committed.status_code == 200, committed.text
    assert committed.json()["status"] == "completed_with_errors"
    assert "partial_import" in committed.json()["quality_flags"]
    errors = client.get(f"/api/v1/imports/{batch_id}/errors")
    assert errors.status_code == 200, errors.text
    assert "bad-1" in errors.text
    assert _rows(admin, "SELECT count(*) FROM cash_transactions")[0][0] == 1


def test_stranger_and_empty_and_older_statement(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id, user_id = _ready(client, admin, app, fake, tmp_path, "mail@example.com")
    wallet_id = _wallet(client, company_id)
    source = _mailbox(client, company_id, wallet_id)
    refused = client.post(f"/api/v1/companies/{company_id}/sources/{source['id']}/sync")
    assert refused.status_code == 409
    assert refused.json()["code"] == "imap_disabled"
    stranger = _letter(b"not-a-statement", 2, sender="other@example.com")
    assert _ingest(app, tenant_id, user_id, source["id"], FakeMailbox([stranger]), RECEIVED) == 0
    assert _rows(admin, "SELECT status FROM email_ingestions")[0][0] == "ignored"
    assert _rows(admin, "SELECT count(*) FROM import_batches")[0][0] == 0
    broken = FakeMailbox([], fail=True)
    assert _ingest(app, tenant_id, user_id, source["id"], broken, RECEIVED) == 0
    assert _rows(admin, "SELECT last_error FROM source_connections")[0][0] == "нет связи"
    empty = _statement("13.10.2026")
    _ingest(app, tenant_id, user_id, source["id"], FakeMailbox([_letter(empty, 3)]), RECEIVED)
    batch_id = _rows(admin, "SELECT batch_id FROM email_ingestions WHERE status = 'preview'")[0][0]
    committed = client.post(f"/api/v1/imports/{batch_id}/commit")
    assert committed.status_code == 200, committed.text
    assert _rows(admin, "SELECT count(*) FROM cash_transactions")[0][0] == 0
    covered = _rows(admin, "SELECT coverage_through::text FROM source_connections")[0][0]
    assert covered == "2026-10-13"
    older = _statement("01.10.2026", _document("old-1", "01.10.2026", valid=True))
    _ingest(app, tenant_id, user_id, source["id"], FakeMailbox([_letter(older, 4)]), RECEIVED)
    older_id = _rows(admin, "SELECT batch_id FROM email_ingestions WHERE uid = 4")[0][0]
    again = client.post(f"/api/v1/imports/{older_id}/commit")
    assert again.status_code == 200, again.text
    stayed = _rows(admin, "SELECT coverage_through::text FROM source_connections")[0][0]
    assert stayed == "2026-10-13"


def test_digest_waits_thirty_minutes(client, admin, app, fake, tmp_path) -> None:
    freeze(app, SLOT)
    tenant_id, company_id, _user_id = _ready(
        client, admin, app, fake, tmp_path, "digest-mail@example.com"
    )
    wallet_id = _wallet(client, company_id)
    _mailbox(client, company_id, wallet_id)
    token = client.post("/api/v1/telegram/link-token")
    assert token.status_code == 200, token.text
    session = app.state.session_factory()
    try:
        ingest_update(
            session,
            app.state.settings,
            {
                "update_id": 1,
                "message": {
                    "message_id": 1,
                    "text": f"/start {token.json()['token']}",
                    "from": {"id": 901},
                    "chat": {"id": 901, "type": "private"},
                },
            },
            SLOT,
        )
        session.commit()
    finally:
        session.close()
    assert client.post("/api/v1/telegram/binding/confirm").status_code == 200
    assert _schedule(app, SLOT) == 0
    assert _rows(admin, "SELECT count(*) FROM digest_snapshots")[0][0] == 0
    assert _schedule(app, SLOT + timedelta(minutes=30)) == 1
    text_value = _rows(admin, "SELECT payload->>'text' FROM notification_outbox")[0][0]
    assert "Выписка" in text_value
    assert "покрытие нет данных" in text_value
    assert "Выручка вчера: нет данных" in text_value


def _schedule(app, at: datetime) -> int:
    session = app.state.worker_session_factory()
    try:
        created = schedule_digests(session, app.state.settings, at)
        session.commit()
        return created
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
