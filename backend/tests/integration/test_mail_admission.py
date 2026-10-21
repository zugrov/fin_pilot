from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.domain.mail_admission import (
    MailAdmissionOutcome,
    TrustedServerBinding,
    TrustedTransportAuth,
    UntrustedMailEnvelope,
)
from app.services.mail_admission_service import evaluate_mail_admission
from sqlalchemy import text
from tests.integration.conftest import (
    freeze,
    latest_link,
    login,
    open_workspace,
    pay,
    register_and_verify,
    token_from_link,
)

RECEIVED = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
SECRET = "mailbox-secret-1"


def _trusted_transport() -> TrustedTransportAuth:
    return TrustedTransportAuth(
        message_authenticated=True,
        spf="pass",
        dkim="pass",
        dmarc="pass",
    )


def _envelope(from_addr: str) -> UntrustedMailEnvelope:
    return UntrustedMailEnvelope(from_header=from_addr)


def _counts(admin) -> dict[str, int]:
    tables = (
        "ingestion_deliveries",
        "email_ingestions",
        "import_batches",
        "source_identities",
        "transactional_email_outbox",
        "notification_outbox",
    )
    with admin.connect() as connection:
        return {
            name: int(connection.execute(text(f"SELECT count(*) FROM {name}")).scalar_one())
            for name in tables
        }


def _insert_email_source(admin, tenant_id: str, company_id: str) -> str:
    source_id = uuid4()
    with admin.connect() as connection:
        connection.execute(
            text(
                """
                INSERT INTO source_connections (
                  id, tenant_id, company_id, type, name, namespace,
                  format, dataset, status, created_at
                ) VALUES (
                  :id, :tenant_id, :company_id, 'email', 'Gate', 'mail-gate',
                  'clientbank', 'cash', 'active', :at
                )
                """
            ),
            {
                "id": source_id,
                "tenant_id": tenant_id,
                "company_id": company_id,
                "at": RECEIVED,
            },
        )
        connection.commit()
    return str(source_id)


def _ready(client, admin, app, fake, tmp_path, email: str) -> tuple[str, str, str, str]:
    app.state.settings.import_storage_dir = str(tmp_path)
    app.state.settings.poll_imap = False
    app.state.settings.billing_guard_bypass = False
    freeze(app, RECEIVED)
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


def _evaluate(app, tenant_id: str, user_id: str, company_id: str, source_id: str, email: str):
    session = app.state.session_factory()
    try:
        binding = TrustedServerBinding(
            connection_id=UUID(source_id),
            tenant_id=UUID(tenant_id),
            company_id=UUID(company_id),
            actor_user_id=UUID(user_id),
        )
        decision = evaluate_mail_admission(
            session,
            app.state.settings,
            envelope=_envelope(email),
            transport=_trusted_transport(),
            binding=binding,
            at=app.state.clock.now(),
        )
        return decision
    finally:
        session.close()


def test_allow_preview_verified_paid_owner(client, admin, app, fake, tmp_path) -> None:
    email = "owner-mail@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    before = _counts(admin)
    decision = _evaluate(app, tenant_id, user_id, company_id, source_id, email)
    after = _counts(admin)
    assert decision.outcome == MailAdmissionOutcome.ALLOW_PREVIEW, decision.reason_code
    assert decision.reason_code == "ok"
    assert decision.context is not None
    assert str(decision.context.company_id) == company_id
    assert decision.context.sender_normalized == email
    assert before == after


def test_unverified_user_rejects(client, admin, app, fake, tmp_path) -> None:
    email = "unverified@example.com"
    app.state.settings.import_storage_dir = str(tmp_path)
    freeze(app, RECEIVED)
    created = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "long-password-1", "name": "U"},
    )
    assert created.status_code == 200
    logged = login(client, email)
    tenant_id = open_workspace(client)
    company_id = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Фирма", "kind": "company"},
    ).json()["id"]
    source_id = _insert_email_source(admin, tenant_id, company_id)
    before = _counts(admin)
    decision = _evaluate(app, tenant_id, logged["user"]["id"], company_id, source_id, email)
    assert decision.outcome == MailAdmissionOutcome.REJECT
    assert decision.reason_code == "email_not_verified"
    assert before == _counts(admin)


def test_viewer_cannot_admit(client, admin, app, fake, tmp_path) -> None:
    register_and_verify(client, admin, "owner-view@example.com")
    login(client, "owner-view@example.com")
    tenant_id = open_workspace(client)
    invited = client.post(
        f"/api/v1/workspaces/{tenant_id}/invitations",
        json={"email": "viewer-mail@example.com", "role": "viewer"},
    )
    assert invited.status_code == 200
    token = token_from_link(latest_link(admin))
    guest = client.__class__(client.app)
    register_and_verify(guest, admin, "viewer-mail@example.com")
    guest_login = login(guest, "viewer-mail@example.com")
    accepted = guest.post("/api/v1/auth/invitations/accept", json={"token": token})
    assert accepted.status_code == 200
    company_id = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Фирма", "kind": "company"},
    ).json()["id"]
    pay(client, app, fake, 1, "month")
    client.post(f"/api/v1/billing/companies/{company_id}/activate")
    wallet_id = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Расчётный", "type": "bank", "code": "main"},
        headers={"Idempotency-Key": uuid4().hex},
    ).json()["id"]
    source_id = client.post(
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
    ).json()["id"]
    before = _counts(admin)
    decision = _evaluate(
        app,
        tenant_id,
        guest_login["user"]["id"],
        company_id,
        source_id,
        "viewer-mail@example.com",
    )
    assert decision.outcome == MailAdmissionOutcome.REJECT
    assert decision.reason_code == "forbidden"
    assert before == _counts(admin)


def test_unpaid_write_access_rejects(client, admin, app, fake, tmp_path) -> None:
    email = "unpaid@example.com"
    app.state.settings.import_storage_dir = str(tmp_path)
    app.state.settings.billing_guard_bypass = False
    freeze(app, RECEIVED)
    register_and_verify(client, admin, email)
    logged = login(client, email)
    tenant_id = open_workspace(client)
    company_id = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Фирма", "kind": "company"},
    ).json()["id"]
    source_id = _insert_email_source(admin, tenant_id, company_id)
    decision = _evaluate(app, tenant_id, logged["user"]["id"], company_id, source_id, email)
    assert decision.reason_code == "payment_required"


def test_expired_paid_through_rejects(client, admin, app, fake, tmp_path) -> None:
    email = "expired@example.com"
    app.state.settings.billing_guard_bypass = False
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    end = datetime.fromisoformat(client.get("/api/v1/billing/subscription").json()["paid_through"])
    freeze(app, end + timedelta(days=app.state.settings.billing_grace_days + 1))
    decision = _evaluate(app, tenant_id, user_id, company_id, source_id, email)
    assert decision.reason_code == "payment_required"


def test_wrong_tenant_binding_rejects(client, admin, app, fake, tmp_path) -> None:
    email = "tenant-a@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    other = client.__class__(client.app)
    register_and_verify(other, admin, "tenant-b@example.com")
    login(other, "tenant-b@example.com")
    other_tenant = open_workspace(other, "Другое")
    session = app.state.session_factory()
    try:
        binding = TrustedServerBinding(
            connection_id=UUID(source_id),
            tenant_id=UUID(other_tenant),
            company_id=UUID(company_id),
            actor_user_id=UUID(user_id),
        )
        decision = evaluate_mail_admission(
            session,
            app.state.settings,
            envelope=_envelope(email),
            transport=_trusted_transport(),
            binding=binding,
            at=app.state.clock.now(),
        )
    finally:
        session.close()
    assert decision.reason_code in {
        "routing_binding_conflict",
        "not_found",
        "forbidden",
        "source_not_found",
    }


def test_routing_ambiguous_when_from_matches_other_user(
    client, admin, app, fake, tmp_path
) -> None:
    owner_email = "ambig-owner@example.com"
    tenant_id, company_id, owner_id, source_id = _ready(
        client, admin, app, fake, tmp_path, owner_email
    )
    other = client.__class__(client.app)
    other_email = "ambig-other@example.com"
    register_and_verify(other, admin, other_email)
    session = app.state.session_factory()
    try:
        binding = TrustedServerBinding(
            connection_id=UUID(source_id),
            tenant_id=UUID(tenant_id),
            company_id=UUID(company_id),
            actor_user_id=UUID(owner_id),
        )
        decision = evaluate_mail_admission(
            session,
            app.state.settings,
            envelope=_envelope(other_email),
            transport=_trusted_transport(),
            binding=binding,
            at=app.state.clock.now(),
        )
    finally:
        session.close()
    assert decision.outcome == MailAdmissionOutcome.REVIEW
    assert decision.reason_code == "routing_ambiguous"


def test_gate_never_writes_side_effects_on_reject(client, admin, app, fake, tmp_path) -> None:
    email = "sidefx@example.com"
    tenant_id, company_id, user_id, source_id = _ready(
        client, admin, app, fake, tmp_path, email
    )
    before = _counts(admin)
    session = app.state.session_factory()
    try:
        binding = TrustedServerBinding(
            connection_id=UUID(source_id),
            tenant_id=UUID(tenant_id),
            company_id=UUID(company_id),
            actor_user_id=UUID(user_id),
        )
        reject = evaluate_mail_admission(
            session,
            app.state.settings,
            envelope=_envelope("wrong@example.com"),
            transport=_trusted_transport(),
            binding=binding,
            at=app.state.clock.now(),
        )
        allow = evaluate_mail_admission(
            session,
            app.state.settings,
            envelope=_envelope(email),
            transport=_trusted_transport(),
            binding=binding,
            at=app.state.clock.now(),
        )
    finally:
        session.close()
    assert reject.outcome == MailAdmissionOutcome.REJECT
    assert allow.outcome == MailAdmissionOutcome.ALLOW_PREVIEW
    assert before == _counts(admin)
