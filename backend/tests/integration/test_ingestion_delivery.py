import os
import threading
import uuid
from dataclasses import dataclass
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
REVISION = "20261019_0013"
REV_0011 = "20261018_0011"
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
        threads = [threading.Thread(target=worker, args=(f"race-{index}",)) for index in range(2)]
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


@dataclass(frozen=True)
class _ScopeFixtures:
    tenant_id: uuid.UUID
    company_a: uuid.UUID
    company_b: uuid.UUID
    conn_a1: uuid.UUID
    conn_a2: uuid.UUID
    conn_b1: uuid.UUID
    batch_a1: uuid.UUID
    delivery_a1: uuid.UUID
    delivery_a1b: uuid.UUID
    delivery_a2: uuid.UUID
    delivery_b1: uuid.UUID


def _alembic_revision(target: str) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    previous = os.getcwd()
    os.chdir(BACKEND)
    try:
        command.upgrade(config, target)
    finally:
        os.chdir(previous)


def _alembic_downgrade(target: str) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    previous = os.getcwd()
    os.chdir(BACKEND)
    try:
        command.downgrade(config, target)
    finally:
        os.chdir(previous)


def _constraint_exists(connection, name: str) -> bool:
    return (
        connection.execute(
            text("SELECT 1 FROM pg_constraint WHERE conname = :name LIMIT 1"),
            {"name": name},
        ).first()
        is not None
    )


def _expect_fk_violation(connection, sql: str, params: dict, constraint: str) -> None:
    with pytest.raises(IntegrityError) as caught:
        with connection.begin_nested():
            connection.execute(text(sql), params)
    orig = caught.value.orig
    assert isinstance(orig, psycopg.errors.ForeignKeyViolation), orig
    assert orig.diag.constraint_name == constraint, orig.diag.constraint_name
    assert orig.sqlstate == "23503"


def _seed_scope_fixtures(connection) -> _ScopeFixtures:
    tenant_id = uuid.uuid4()
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    wallet_a = uuid.uuid4()
    wallet_b = uuid.uuid4()
    conn_a1 = uuid.uuid4()
    conn_a2 = uuid.uuid4()
    conn_b1 = uuid.uuid4()
    batch_a1 = uuid.uuid4()
    delivery_a1 = uuid.uuid4()
    delivery_a1b = uuid.uuid4()
    delivery_a2 = uuid.uuid4()
    delivery_b1 = uuid.uuid4()
    now = datetime.now(tz=UTC)
    connection.execute(
        text("INSERT INTO tenants (id, name, created_at) VALUES (:id, 'Scope FK', :at)"),
        {"id": tenant_id, "at": now},
    )
    for company_id, name in ((company_a, "A"), (company_b, "B")):
        connection.execute(
            text(
                "INSERT INTO companies "
                "(id, tenant_id, name, kind, created_at, updated_at) "
                "VALUES (:id, :tenant, :name, 'company', :at, :at)"
            ),
            {"id": company_id, "tenant": tenant_id, "name": name, "at": now},
        )
    connection.execute(
        text(
            "INSERT INTO wallets "
            "(id, tenant_id, company_id, name, type, code, currency, availability_type, "
            "minimum_reserve, created_at) "
            "VALUES (:id, :tenant, :company, 'Main', 'bank', :code, 'RUB', "
            "'spendable', 0, :at)"
        ),
        {"id": wallet_a, "tenant": tenant_id, "company": company_a, "code": "a-main", "at": now},
    )
    connection.execute(
        text(
            "INSERT INTO wallets "
            "(id, tenant_id, company_id, name, type, code, currency, availability_type, "
            "minimum_reserve, created_at) "
            "VALUES (:id, :tenant, :company, 'Main', 'bank', :code, 'RUB', "
            "'spendable', 0, :at)"
        ),
        {"id": wallet_b, "tenant": tenant_id, "company": company_b, "code": "b-main", "at": now},
    )
    for source_id, company_id, wallet_id, namespace in (
        (conn_a1, company_a, wallet_a, "scope-a1"),
        (conn_a2, company_a, wallet_a, "scope-a2"),
        (conn_b1, company_b, wallet_b, "scope-b1"),
    ):
        connection.execute(
            text(
                "INSERT INTO source_connections "
                "(id, tenant_id, company_id, type, name, namespace, wallet_id, format, "
                "encoding, dataset, created_at) "
                "VALUES (:id, :tenant, :company, 'file', :name, :namespace, :wallet, "
                "'csv', 'utf-8', 'cash', :at)"
            ),
            {
                "id": source_id,
                "tenant": tenant_id,
                "company": company_id,
                "name": namespace,
                "namespace": namespace,
                "wallet": wallet_id,
                "at": now,
            },
        )
    connection.execute(
        text(
            "INSERT INTO import_batches "
            "(id, tenant_id, company_id, connection_id, file_hash, file_storage_key, "
            "format, status, created_at) "
            "VALUES (:id, :tenant, :company, :conn, 'hash-a1', 'key-a1', 'csv', "
            "'preview_ready', :at)"
        ),
        {
            "id": batch_a1,
            "tenant": tenant_id,
            "company": company_a,
            "conn": conn_a1,
            "at": now,
        },
    )
    for delivery_id, company_id, conn_id, key in (
        (delivery_a1, company_a, conn_a1, "del-a1"),
        (delivery_a1b, company_a, conn_a1, "del-a1b"),
        (delivery_a2, company_a, conn_a2, "del-a2"),
        (delivery_b1, company_b, conn_b1, "del-b1"),
    ):
        connection.execute(
            text(
                "INSERT INTO ingestion_deliveries "
                "(id, tenant_id, company_id, connection_id, channel, delivery_key, "
                "request_fingerprint, transport_status, created_at, updated_at) "
                "VALUES (:id, :tenant, :company, :conn, 'ui', :key, 'fp', "
                "'partially_received', :at, :at)"
            ),
            {
                "id": delivery_id,
                "tenant": tenant_id,
                "company": company_id,
                "conn": conn_id,
                "key": key,
                "at": now,
            },
        )
    return _ScopeFixtures(
        tenant_id=tenant_id,
        company_a=company_a,
        company_b=company_b,
        conn_a1=conn_a1,
        conn_a2=conn_a2,
        conn_b1=conn_b1,
        batch_a1=batch_a1,
        delivery_a1=delivery_a1,
        delivery_a1b=delivery_a1b,
        delivery_a2=delivery_a2,
        delivery_b1=delivery_b1,
    )


def _insert_part(
    connection,
    *,
    part_id: uuid.UUID,
    fixtures: _ScopeFixtures,
    delivery_id: uuid.UUID,
    company_id: uuid.UUID,
    connection_id: uuid.UUID,
    batch_id: uuid.UUID | None,
    part_index: int,
) -> None:
    now = datetime.now(tz=UTC)
    connection.execute(
        text(
            "INSERT INTO ingestion_delivery_parts "
            "(id, tenant_id, delivery_id, company_id, connection_id, part_index, "
            "content_hash, batch_id, part_status, created_at, updated_at) "
            "VALUES (:id, :tenant, :delivery, :company, :conn, :idx, 'hash', "
            ":batch, 'preview', :at, :at)"
        ),
        {
            "id": part_id,
            "tenant": fixtures.tenant_id,
            "delivery": delivery_id,
            "company": company_id,
            "conn": connection_id,
            "idx": part_index,
            "batch": batch_id,
            "at": now,
        },
    )


def test_scope_part_batch_rejects_different_connection(migrated_database) -> None:
    assert_finpilot_test_database(migrated_database)
    with migrated_database.begin() as connection:
        fixtures = _seed_scope_fixtures(connection)
        _expect_fk_violation(
            connection,
            "INSERT INTO ingestion_delivery_parts "
            "(id, tenant_id, delivery_id, company_id, connection_id, part_index, "
            "content_hash, batch_id, part_status, created_at, updated_at) "
            "VALUES (:id, :tenant, :delivery, :company, :conn, 1, 'hash', :batch, "
            "'preview', now(), now())",
            {
                "id": uuid.uuid4(),
                "tenant": fixtures.tenant_id,
                "delivery": fixtures.delivery_a2,
                "company": fixtures.company_a,
                "conn": fixtures.conn_a2,
                "batch": fixtures.batch_a1,
            },
            "ingestion_delivery_parts_batch_scope_fk",
        )
        assert connection.execute(text("SELECT count(*) FROM import_batches")).scalar_one() == 1


def test_scope_part_batch_rejects_different_company(migrated_database) -> None:
    assert_finpilot_test_database(migrated_database)
    with migrated_database.begin() as connection:
        fixtures = _seed_scope_fixtures(connection)
        _expect_fk_violation(
            connection,
            "INSERT INTO ingestion_delivery_parts "
            "(id, tenant_id, delivery_id, company_id, connection_id, part_index, "
            "content_hash, batch_id, part_status, created_at, updated_at) "
            "VALUES (:id, :tenant, :delivery, :company, :conn, 1, 'hash', :batch, "
            "'preview', now(), now())",
            {
                "id": uuid.uuid4(),
                "tenant": fixtures.tenant_id,
                "delivery": fixtures.delivery_b1,
                "company": fixtures.company_b,
                "conn": fixtures.conn_b1,
                "batch": fixtures.batch_a1,
            },
            "ingestion_delivery_parts_batch_scope_fk",
        )


def test_scope_batch_delivery_rejects_different_connection(migrated_database) -> None:
    assert_finpilot_test_database(migrated_database)
    with migrated_database.begin() as connection:
        fixtures = _seed_scope_fixtures(connection)
        _expect_fk_violation(
            connection,
            "UPDATE import_batches SET delivery_id = :delivery WHERE id = :batch",
            {"delivery": fixtures.delivery_a2, "batch": fixtures.batch_a1},
            "import_batches_delivery_scope_fk",
        )


def test_scope_delivery_rejects_foreign_connection(migrated_database) -> None:
    assert_finpilot_test_database(migrated_database)
    with migrated_database.begin() as connection:
        fixtures = _seed_scope_fixtures(connection)
        _expect_fk_violation(
            connection,
            "INSERT INTO ingestion_deliveries "
            "(id, tenant_id, company_id, connection_id, channel, delivery_key, "
            "request_fingerprint, transport_status, created_at, updated_at) "
            "VALUES (:id, :tenant, :company, :conn, 'ui', 'bad-del', 'fp', "
            "'partially_received', now(), now())",
            {
                "id": uuid.uuid4(),
                "tenant": fixtures.tenant_id,
                "company": fixtures.company_a,
                "conn": fixtures.conn_b1,
            },
            "ingestion_deliveries_connection_fk",
        )


def test_scope_batch_delivery_rejects_different_company(migrated_database) -> None:
    assert_finpilot_test_database(migrated_database)
    with migrated_database.begin() as connection:
        fixtures = _seed_scope_fixtures(connection)
        batch_b = uuid.uuid4()
        now = datetime.now(tz=UTC)
        connection.execute(
            text(
                "INSERT INTO import_batches "
                "(id, tenant_id, company_id, connection_id, file_hash, file_storage_key, "
                "format, status, created_at) "
                "VALUES (:id, :tenant, :company, :conn, 'hash-b1', 'key-b1', 'csv', "
                "'preview_ready', :at)"
            ),
            {
                "id": batch_b,
                "tenant": fixtures.tenant_id,
                "company": fixtures.company_b,
                "conn": fixtures.conn_b1,
                "at": now,
            },
        )
        _expect_fk_violation(
            connection,
            "UPDATE import_batches SET delivery_id = :delivery WHERE id = :batch",
            {"delivery": fixtures.delivery_a1, "batch": batch_b},
            "import_batches_delivery_scope_fk",
        )


def test_scope_email_ingestion_rejects_different_connection(migrated_database) -> None:
    assert_finpilot_test_database(migrated_database)
    with migrated_database.begin() as connection:
        fixtures = _seed_scope_fixtures(connection)
        email_conn = uuid.uuid4()
        now = datetime.now(tz=UTC)
        connection.execute(
            text(
                "INSERT INTO source_connections "
                "(id, tenant_id, company_id, type, name, namespace, wallet_id, format, "
                "encoding, dataset, created_at) "
                "VALUES (:id, :tenant, :company, 'email', 'mail', 'scope-mail', "
                "(SELECT id FROM wallets WHERE tenant_id = :tenant AND company_id = :company "
                "LIMIT 1), 'clientbank', 'utf-8', 'cash', :at)"
            ),
            {
                "id": email_conn,
                "tenant": fixtures.tenant_id,
                "company": fixtures.company_a,
                "at": now,
            },
        )
        _expect_fk_violation(
            connection,
            "INSERT INTO email_ingestions "
            "(id, tenant_id, connection_id, delivery_id, uidvalidity, uid, "
            "attachment_hash, status, created_at) "
            "VALUES (:id, :tenant, :conn, :delivery, 1, 1, 'att', 'preview', :at)",
            {
                "id": uuid.uuid4(),
                "tenant": fixtures.tenant_id,
                "conn": email_conn,
                "delivery": fixtures.delivery_a1,
                "at": now,
            },
            "email_ingestions_delivery_scope_fk",
        )


def test_scope_allows_shared_batch_and_legacy_null_delivery(migrated_database) -> None:
    assert_finpilot_test_database(migrated_database)
    with migrated_database.begin() as connection:
        fixtures = _seed_scope_fixtures(connection)
        part_one = uuid.uuid4()
        part_two = uuid.uuid4()
        _insert_part(
            connection,
            part_id=part_one,
            fixtures=fixtures,
            delivery_id=fixtures.delivery_a1,
            company_id=fixtures.company_a,
            connection_id=fixtures.conn_a1,
            batch_id=fixtures.batch_a1,
            part_index=1,
        )
        _insert_part(
            connection,
            part_id=part_two,
            fixtures=fixtures,
            delivery_id=fixtures.delivery_a1b,
            company_id=fixtures.company_a,
            connection_id=fixtures.conn_a1,
            batch_id=fixtures.batch_a1,
            part_index=1,
        )
        connection.execute(
            text("UPDATE import_batches SET delivery_id = :delivery WHERE id = :batch"),
            {"delivery": fixtures.delivery_a1, "batch": fixtures.batch_a1},
        )
        legacy_batch = uuid.uuid4()
        now = datetime.now(tz=UTC)
        connection.execute(
            text(
                "INSERT INTO import_batches "
                "(id, tenant_id, company_id, connection_id, delivery_id, file_hash, "
                "file_storage_key, format, status, created_at) "
                "VALUES (:id, :tenant, :company, :conn, NULL, 'legacy', 'legacy-key', "
                "'csv', 'preview_ready', :at)"
            ),
            {
                "id": legacy_batch,
                "tenant": fixtures.tenant_id,
                "company": fixtures.company_a,
                "conn": fixtures.conn_a1,
                "at": now,
            },
        )
        assert (
            connection.execute(
                text(
                    "SELECT count(DISTINCT batch_id) FROM ingestion_delivery_parts "
                    "WHERE batch_id IS NOT NULL"
                )
            ).scalar_one()
            == 1
        )
        assert (
            connection.execute(
                text("SELECT delivery_id IS NULL FROM import_batches WHERE id = :id"),
                {"id": legacy_batch},
            ).scalar_one()
            is True
        )


def test_scope_fk_gap_on_0011_then_enforced_on_0012(migrated_database) -> None:
    assert_finpilot_test_database(migrated_database)
    _alembic_downgrade(REV_0011)
    try:
        gap_part = uuid.uuid4()
        with migrated_database.begin() as connection:
            fixtures = _seed_scope_fixtures(connection)
            with connection.begin_nested():
                _insert_part(
                    connection,
                    part_id=gap_part,
                    fixtures=fixtures,
                    delivery_id=fixtures.delivery_a2,
                    company_id=fixtures.company_a,
                    connection_id=fixtures.conn_a2,
                    batch_id=fixtures.batch_a1,
                    part_index=1,
                )
            connection.execute(
                text("DELETE FROM ingestion_delivery_parts WHERE id = :id"),
                {"id": gap_part},
            )
        _alembic_revision(REVISION)
        with migrated_database.begin() as connection:
            fixtures = _seed_scope_fixtures(connection)
            _expect_fk_violation(
                connection,
                "INSERT INTO ingestion_delivery_parts "
                "(id, tenant_id, delivery_id, company_id, connection_id, part_index, "
                "content_hash, batch_id, part_status, created_at, updated_at) "
                "VALUES (:id, :tenant, :delivery, :company, :conn, 1, 'hash', :batch, "
                "'preview', now(), now())",
                {
                    "id": uuid.uuid4(),
                    "tenant": fixtures.tenant_id,
                    "delivery": fixtures.delivery_a2,
                    "company": fixtures.company_a,
                    "conn": fixtures.conn_a2,
                    "batch": fixtures.batch_a1,
                },
                "ingestion_delivery_parts_batch_scope_fk",
            )
    finally:
        _alembic_revision(REVISION)


def test_migration_0012_downgrade_restores_0011_constraints(migrated_database) -> None:
    assert_finpilot_test_database(migrated_database)
    _alembic_revision(REVISION)
    try:
        with migrated_database.connect() as connection:
            assert _constraint_exists(connection, "ingestion_delivery_parts_batch_scope_fk")
        _alembic_downgrade(REV_0011)
        with migrated_database.connect() as connection:
            assert _constraint_exists(connection, "ingestion_delivery_parts_batch_fk")
            assert not _constraint_exists(connection, "ingestion_delivery_parts_batch_scope_fk")
            assert _constraint_exists(connection, "import_batches_delivery_fk")
            assert not _constraint_exists(connection, "import_batches_delivery_scope_fk")
    finally:
        _alembic_revision(REVISION)


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
