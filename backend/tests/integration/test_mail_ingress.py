from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.domain.mail_admission import (
    TrustedServerBinding,
    TrustedTransportAuth,
)
from app.domain.mail_ingress import (
    MailDeliverySlot,
    MailIngressStage,
    TrustedIngressBundle,
    build_simple_mime,
    raw_message_digest,
)
from app.services.mail_ingress_service import ingest_trusted_local_mail
from sqlalchemy import text
from tests.integration.conftest import (
    freeze,
    login,
    open_workspace,
    pay,
    register_and_verify,
)

RECEIVED = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
SECRET = "mailbox-secret-1"


def _trusted() -> TrustedTransportAuth:
    return TrustedTransportAuth(
        message_authenticated=True,
        spf="pass",
        dkim="pass",
        dmarc="pass",
    )


def _statement(end: str, documents: str = "") -> bytes:
    return (
        f"1CClientBankExchange\nВерсияФормата=1.03\nДатаКонца={end}\n{documents}КонецФайла\n"
    ).encode()


def _document(number: str, day: str) -> str:
    return (
        "СекцияДокумент=Платежное поручение\n"
        f"Номер={number}\n"
        "Сумма=10.00\n"
        f"ДатаПоступило={day}\n"
        "КонецДокумента\n"
    )


def _counts(admin) -> dict[str, int]:
    tables = (
        "ingestion_deliveries",
        "email_ingestions",
        "import_batches",
        "raw_import_rows",
        "source_identities",
        "cash_transactions",
        "transactional_email_outbox",
        "notification_outbox",
    )
    with admin.connect() as connection:
        return {
            name: int(connection.execute(text(f"SELECT count(*) FROM {name}")).scalar_one())
            for name in tables
        }


def _ready(client, admin, app, fake, tmp_path, email: str) -> tuple[str, str, str, str]:
    app.state.settings.import_storage_dir = str(tmp_path)
    app.state.settings.poll_imap = False
    app.state.settings.billing_guard_bypass = False
    freeze(app, RECEIVED)
    register_and_verify(client, admin, email)
    logged = login(client, email)
    tenant_id = open_workspace(client, "Ingress")
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
    source = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Выписка",
            "type": "email",
            "namespace": "mail-bank",
            "format": "clientbank",
            "wallet_id": wallet.json()["id"],
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
    assert source.status_code == 200, source.text
    return tenant_id, company_id, logged["user"]["id"], source.json()["id"]


def _bundle(
    tenant_id: str,
    company_id: str,
    user_id: str,
    source_id: str,
    raw: bytes,
    *,
    uid: int,
    uidvalidity: int = 4,
) -> TrustedIngressBundle:
    return TrustedIngressBundle(
        transport=_trusted(),
        binding=TrustedServerBinding(
            connection_id=UUID(source_id),
            tenant_id=UUID(tenant_id),
            company_id=UUID(company_id),
            actor_user_id=UUID(user_id),
        ),
        delivery_slot=MailDeliverySlot(uidvalidity=uidvalidity, uid=uid),
        message_digest=raw_message_digest(raw),
    )


def _ingest(app, raw: bytes, bundle: TrustedIngressBundle):
    session = app.state.session_factory()
    try:
        result = ingest_trusted_local_mail(
            session,
            app.state.settings,
            raw_message=raw,
            bundle=bundle,
            at=app.state.clock.now(),
        )
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def test_allow_preview_creates_delivery_and_preview(client, admin, app, fake, tmp_path) -> None:
    email = "ingress-ok@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    content = _statement("13.10.2026", _document("ok-1", "13.10.2026"))
    raw = build_simple_mime(
        from_addr=email,
        attachment_name="stmt.txt",
        attachment_bytes=content,
        message_id="<ingress-1@local>",
    )
    before = _counts(admin)
    result = _ingest(app, raw, _bundle(tenant_id, company_id, user_id, source_id, raw, uid=11))
    after = _counts(admin)
    assert result.stage == MailIngressStage.PREVIEW
    assert result.reason_code == "ok"
    assert result.preview_created is True
    assert result.delivery_id is not None
    assert len(result.batch_ids) == 1
    assert after["ingestion_deliveries"] == before["ingestion_deliveries"] + 1
    assert after["import_batches"] == before["import_batches"] + 1
    assert after["email_ingestions"] == before["email_ingestions"] + 1
    assert after["cash_transactions"] == before["cash_transactions"]
    assert after["source_identities"] == before["source_identities"]


def test_reject_does_not_call_receive_import(
    client, admin, app, fake, tmp_path, monkeypatch
) -> None:
    email = "ingress-reject@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    calls: list[int] = []

    def _spy(*args, **kwargs):
        calls.append(1)
        raise AssertionError("receive_import")

    monkeypatch.setattr("app.services.mail_service.receive_import", _spy)
    raw = build_simple_mime(
        from_addr="wrong@example.com",
        attachment_name="stmt.txt",
        attachment_bytes=b"x",
    )
    before = _counts(admin)
    result = _ingest(app, raw, _bundle(tenant_id, company_id, user_id, source_id, raw, uid=12))
    assert result.stage == MailIngressStage.REJECTED
    assert calls == []
    assert _counts(admin) == before


def test_disabled_source_rejects_before_import(client, admin, app, fake, tmp_path) -> None:
    email = "ingress-disabled@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    with admin.connect() as connection:
        connection.execute(
            text("UPDATE source_connections SET enabled = false WHERE id = :id"),
            {"id": source_id},
        )
        connection.commit()
    raw = build_simple_mime(
        from_addr=email,
        attachment_name="stmt.txt",
        attachment_bytes=_statement("13.10.2026", _document("d-1", "13.10.2026")),
    )
    before = _counts(admin)
    result = _ingest(app, raw, _bundle(tenant_id, company_id, user_id, source_id, raw, uid=13))
    assert result.reason_code == "source_disabled"
    assert _counts(admin) == before


def test_repeat_same_delivery_is_idempotent(client, admin, app, fake, tmp_path) -> None:
    email = "ingress-repeat@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    content = _statement("13.10.2026", _document("rep-1", "13.10.2026"))
    raw = build_simple_mime(from_addr=email, attachment_name="stmt.txt", attachment_bytes=content)
    bundle = _bundle(tenant_id, company_id, user_id, source_id, raw, uid=14)
    first = _ingest(app, raw, bundle)
    second = _ingest(app, raw, bundle)
    assert first.preview_created is True
    assert second.preview_created is False
    with admin.connect() as connection:
        deliveries = connection.execute(
            text("SELECT count(*) FROM ingestion_deliveries")
        ).scalar_one()
        batches = connection.execute(text("SELECT count(*) FROM import_batches")).scalar_one()
    assert deliveries == 1
    assert batches == 1


def test_content_conflict_on_same_transport_key(client, admin, app, fake, tmp_path) -> None:
    email = "ingress-conflict@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    first_raw = build_simple_mime(
        from_addr=email,
        attachment_name="stmt.txt",
        attachment_bytes=_statement("13.10.2026", _document("c-1", "13.10.2026")),
    )
    bundle = _bundle(tenant_id, company_id, user_id, source_id, first_raw, uid=15)
    assert _ingest(app, first_raw, bundle).stage == MailIngressStage.PREVIEW
    second_raw = build_simple_mime(
        from_addr=email,
        attachment_name="stmt.txt",
        attachment_bytes=_statement("14.10.2026", _document("c-2", "14.10.2026")),
    )
    swapped = TrustedIngressBundle(
        transport=bundle.transport,
        binding=bundle.binding,
        delivery_slot=bundle.delivery_slot,
        message_digest=raw_message_digest(second_raw),
    )
    conflict = _ingest(app, second_raw, swapped)
    assert conflict.reason_code == "delivery_conflict"


def test_same_message_id_different_delivery_slots(client, admin, app, fake, tmp_path) -> None:
    email = "ingress-mid@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    content = _statement("13.10.2026", _document("m-1", "13.10.2026"))
    raw1 = build_simple_mime(
        from_addr=email,
        attachment_name="stmt.txt",
        attachment_bytes=content,
        message_id="<same-mid@bank>",
    )
    raw2 = build_simple_mime(
        from_addr=email,
        attachment_name="stmt.txt",
        attachment_bytes=content,
        message_id="<same-mid@bank>",
    )
    one = _ingest(app, raw1, _bundle(tenant_id, company_id, user_id, source_id, raw1, uid=16))
    two = _ingest(app, raw2, _bundle(tenant_id, company_id, user_id, source_id, raw2, uid=17))
    assert one.stage == MailIngressStage.PREVIEW
    assert two.stage == MailIngressStage.PREVIEW
    with admin.connect() as connection:
        deliveries = connection.execute(
            text("SELECT count(*) FROM ingestion_deliveries")
        ).scalar_one()
    assert deliveries == 2


def test_wrong_binding_rejects(client, admin, app, fake, tmp_path) -> None:
    email = "ingress-bind@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    other = client.__class__(client.app)
    register_and_verify(other, admin, "other-bind@example.com")
    login(other, "other-bind@example.com")
    other_tenant = open_workspace(other, "Чужое")
    raw = build_simple_mime(
        from_addr=email,
        attachment_name="stmt.txt",
        attachment_bytes=_statement("13.10.2026", _document("b-1", "13.10.2026")),
    )
    bundle = TrustedIngressBundle(
        transport=_trusted(),
        binding=TrustedServerBinding(
            connection_id=UUID(source_id),
            tenant_id=UUID(other_tenant),
            company_id=UUID(company_id),
            actor_user_id=UUID(user_id),
        ),
        delivery_slot=MailDeliverySlot(uidvalidity=4, uid=18),
        message_digest=raw_message_digest(raw),
    )
    before = _counts(admin)
    result = _ingest(app, raw, bundle)
    assert result.stage == MailIngressStage.REJECTED
    assert _counts(admin) == before


def test_replay_after_payment_lapse_is_blocked(client, admin, app, fake, tmp_path) -> None:
    email = "ingress-lapse@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    content = _statement("13.10.2026", _document("l-1", "13.10.2026"))
    raw = build_simple_mime(from_addr=email, attachment_name="stmt.txt", attachment_bytes=content)
    bundle = _bundle(tenant_id, company_id, user_id, source_id, raw, uid=19)
    assert _ingest(app, raw, bundle).stage == MailIngressStage.PREVIEW
    end = datetime.fromisoformat(client.get("/api/v1/billing/subscription").json()["paid_through"])
    freeze(app, end + timedelta(days=app.state.settings.billing_grace_days + 1))
    blocked = _ingest(app, raw, bundle)
    assert blocked.reason_code == "payment_required"
    with admin.connect() as connection:
        batches = connection.execute(text("SELECT count(*) FROM import_batches")).scalar_one()
    assert batches == 1
