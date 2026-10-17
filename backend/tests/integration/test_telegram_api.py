from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.integrations.telegram import MockTelegram, SendOutcome
from app.services.telegram_bot import ingest_update
from app.services.telegram_digest import consider_urgent, schedule_digests
from app.services.telegram_dispatch import dispatch_outbox
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.integration.conftest import (
    PASSWORD,
    freeze,
    login,
    open_workspace,
    pay,
    register_and_verify,
    token_from_link,
)

MORNING = datetime(2026, 10, 14, 5, 30, tzinfo=UTC)
TELEGRAM_USER = 501


def _ready(client, admin, app, fake, tmp_path, email: str, companies: int = 1) -> tuple[str, str]:
    freeze(app, MORNING)
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Телеграм")
    company = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Альфа", "kind": "company"},
    )
    assert company.status_code == 200, company.text
    pay(client, app, fake, companies, "month")
    activated = client.post(f"/api/v1/billing/companies/{company.json()['id']}/activate")
    assert activated.status_code == 200, activated.text
    return tenant_id, company.json()["id"]


def _wallet(client, company_id: str, wallet_type: str, amount: str | None) -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": wallet_type, "type": wallet_type, "code": wallet_type},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    if amount is not None:
        opened = client.post(
            f"/api/v1/wallets/{created.json()['id']}/opening-balance",
            json={"effective_at": "2026-10-01T00:00:00+00:00", "amount": amount},
            headers={"Idempotency-Key": uuid4().hex},
        )
        assert opened.status_code == 200, opened.text
    return created.json()


def _plan(client, company_id: str, amount: str) -> None:
    created = client.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json={
            "direction": "out",
            "amount": amount,
            "due_date": "2026-10-20",
            "expected_date": "2026-10-20",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text


def _ingest(app, update: dict, at: datetime) -> list[dict]:
    session = app.state.session_factory()
    try:
        replies = ingest_update(session, app.state.settings, update, at)
        session.commit()
        return replies
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _message(update_id: int, text_value: str, user_id: int = TELEGRAM_USER) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "text": text_value,
            "from": {"id": user_id},
            "chat": {"id": user_id, "type": "private"},
        },
    }


def _click(update_id: int, data: str, user_id: int = TELEGRAM_USER) -> dict:
    return {
        "update_id": update_id,
        "callback_query": {
            "id": str(update_id),
            "data": data,
            "from": {"id": user_id},
        },
    }


def _button(replies: list[dict], label: str) -> str:
    for reply in replies:
        for button in reply["buttons"]:
            if button["label"] == label:
                return button["data"]
    raise AssertionError(f"{label} not in {replies}")


def _link(client, app, at: datetime, user_id: int = TELEGRAM_USER) -> None:
    token = client.post("/api/v1/telegram/link-token")
    assert token.status_code == 200, token.text
    assert token.json()["deep_link"] is None
    assert "200000" not in token.json()["token"]
    started = _ingest(app, _message(1, f"/start {token.json()['token']}", user_id), at)
    assert "Финансовые данные не отправлены" in started[0]["text"]
    confirmed = client.post("/api/v1/telegram/binding/confirm")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["status"] == "active"


def _rows(admin, query: str) -> list:
    with admin.connect() as connection:
        return list(connection.execute(text(query)).all())


def test_t1_expired_and_used_token_do_not_bind(client, admin, app, fake, tmp_path) -> None:
    _ready(client, admin, app, fake, tmp_path, "t1@example.com")
    token = client.post("/api/v1/telegram/link-token")
    raw = token.json()["token"]
    late = datetime.fromisoformat(token.json()["expires_at"]) + timedelta(seconds=1)
    expired = _ingest(app, _message(11, f"/start {raw}"), late)
    assert "недействительна" in expired[0]["text"]
    fresh = client.post("/api/v1/telegram/link-token").json()["token"]
    _ingest(app, _message(12, f"/start {fresh}"), MORNING)
    again = _ingest(app, _message(13, f"/start {fresh}"), MORNING)
    assert "недействительна" in again[0]["text"]
    assert client.get("/api/v1/telegram/binding").json()["status"] == "pending"
    pending = _rows(admin, "SELECT count(*) FROM telegram_bindings WHERE status = 'pending'")
    assert pending[0][0] == 1


def test_t2_pending_binding_has_no_finance(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "t2@example.com")
    _wallet(client, company_id, "cash", "200000.00")
    token = client.post("/api/v1/telegram/link-token").json()["token"]
    _ingest(app, _message(21, f"/start {token}"), MORNING)
    assert client.get("/api/v1/telegram/binding").json()["status"] == "pending"
    balance = _ingest(app, _message(22, "/balance"), MORNING)
    assert "200000" not in balance[0]["text"]
    assert "Финансовые данные не отправлены" in balance[0]["text"]
    preview = client.post("/api/v1/telegram/digest-preview")
    assert preview.status_code == 409


def test_t3_and_t11_add_posts_cash_and_drafts_bank(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "t3@example.com")
    _wallet(client, company_id, "cash", "100000.00")
    _wallet(client, company_id, "bank", "100000.00")
    _link(client, app, MORNING)
    _add(app, "cash", "1000,50", 30)
    statuses = _rows(
        admin, "SELECT status, source, amount FROM cash_transactions ORDER BY created_at"
    )
    assert statuses == [("posted", "telegram", 1000)] or _money_rows(statuses)[0] == (
        "posted",
        "telegram",
        "1000.50",
    )
    before = client.get(f"/api/v1/companies/{company_id}/cash-summary")
    _add(app, "bank", "5000", 40)
    after = client.get(f"/api/v1/companies/{company_id}/cash-summary")
    assert before.json()["cash_total"] == after.json()["cash_total"]
    bank = _rows(
        admin,
        "SELECT status FROM cash_transactions WHERE amount = 5000",
    )
    assert bank == [("draft",)]
    assert _rows(admin, "SELECT count(*) FROM cash_transactions WHERE amount = 1000.50")[0][0] == 1


def test_t4_one_snapshot_for_two_workers(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "t4@example.com")
    _wallet(client, company_id, "cash", "100000.00")
    _link(client, app, MORNING)
    first = _schedule(app, MORNING)
    second = _schedule(app, MORNING)
    assert first == 1
    assert second == 0
    assert _rows(admin, "SELECT count(*) FROM digest_snapshots WHERE kind = 'scheduled'")[0][0] == 1
    late = _schedule(app, datetime(2026, 10, 15, 8, 0, tzinfo=UTC))
    assert late == 0
    marked = _rows(admin, "SELECT last_scheduled_for FROM digest_subscriptions")
    assert str(marked[0][0]) == "2026-10-15"


def test_t5_revoked_access_cancels_before_send(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "t5@example.com")
    _wallet(client, company_id, "cash", "100000.00")
    _link(client, app, MORNING)
    _schedule(app, MORNING)
    transport = MockTelegram()
    _dispatch(app, transport, datetime(2030, 1, 1, tzinfo=UTC))
    assert transport.sent == []
    assert _rows(admin, "SELECT status FROM notification_outbox")[0][0] == "cancelled"


def test_t6_retry_forbidden_and_unknown(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "t6@example.com")
    _wallet(client, company_id, "cash", "100000.00")
    _link(client, app, MORNING)
    _schedule(app, MORNING)
    retry = MockTelegram([SendOutcome("retry", retry_after=30, error="429")])
    _dispatch(app, retry, MORNING)
    assert len(retry.sent) == 1
    assert _rows(admin, "SELECT status FROM notification_outbox")[0][0] == "retry"
    early = MockTelegram()
    _dispatch(app, early, MORNING + timedelta(seconds=10))
    assert early.sent == []
    forbidden = MockTelegram([SendOutcome("forbidden", error="403")])
    _dispatch(app, forbidden, MORNING + timedelta(seconds=31))
    assert client.get("/api/v1/telegram/binding").json()["status"] == "revoked"
    queued = _rows(admin, "SELECT status FROM notification_outbox")
    assert all(row[0] == "cancelled" for row in queued)


def test_t6_unknown_is_not_resent(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "t6b@example.com")
    _wallet(client, company_id, "cash", "100000.00")
    _link(client, app, MORNING, user_id=502)
    _schedule(app, MORNING)
    unknown = MockTelegram([SendOutcome("unknown", error="timeout")])
    _dispatch(app, unknown, MORNING)
    again = MockTelegram()
    _dispatch(app, again, MORNING + timedelta(hours=1))
    assert len(unknown.sent) == 1
    assert again.sent == []
    assert _rows(admin, "SELECT status FROM notification_outbox")[0][0] == "unknown"


def test_t7_and_t8_escape_snapshot_and_do_not_replace_revenue(
    client, admin, app, fake, tmp_path
) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "t8@example.com")
    renamed = client.patch(
        f"/api/v1/companies/{company_id}",
        json={"name": "<Альфа>"},
    )
    if renamed.status_code != 200:
        with admin.begin() as connection:
            connection.execute(
                text("UPDATE companies SET name = :name WHERE id = :id"),
                {"name": "<Альфа>", "id": company_id},
            )
    _wallet(client, company_id, "cash", "200000.00")
    paid = client.post(
        f"/api/v1/companies/{company_id}/transactions",
        json={
            "wallet_id": str(_rows(admin, "SELECT id FROM wallets LIMIT 1")[0][0]),
            "business_date": "2026-10-13",
            "direction": "in",
            "amount": "96000.00",
            "description": "поступление",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert paid.status_code == 200, paid.text
    source = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Продажи",
            "type": "file",
            "namespace": "sales",
            "format": "csv",
            "dataset": "revenue",
        },
    )
    assert source.status_code == 200, source.text
    covered = client.post(
        f"/api/v1/companies/{company_id}/sources/{source.json()['id']}/coverage",
        json={"coverage_through": "2026-10-01"},
    )
    assert covered.status_code == 200, covered.text
    _link(client, app, MORNING, user_id=503)
    _schedule(app, MORNING)
    payload = _rows(
        admin, "SELECT payload->>'text', payload->>'content_hash' FROM notification_outbox"
    )
    text_value = payload[0][0]
    assert "&lt;Альфа&gt;" in text_value
    assert "<Альфа>" not in text_value
    assert "Выручка вчера: нет данных" in text_value
    assert "Выручка вчера: 96000.00" not in text_value
    assert "покрытие только 2026-10-01" in text_value
    assert all(len(row[0]) <= 3500 for row in payload)
    assert len({row[1] for row in payload}) == 1
    assert "fp_session" not in text_value


def test_t9_stop_cancels_queue(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "t9@example.com")
    _wallet(client, company_id, "cash", "100000.00")
    _link(client, app, MORNING, user_id=504)
    _schedule(app, MORNING)
    stopped = _ingest(app, _message(90, "/stop", 504), MORNING)
    assert "отменена" in stopped[0]["text"]
    assert _rows(admin, "SELECT status FROM notification_outbox")[0][0] == "cancelled"
    transport = MockTelegram()
    _dispatch(app, transport, MORNING)
    assert transport.sent == []


def test_t12_group_keeps_company_risk(client, admin, app, fake, tmp_path) -> None:
    tenant, first = _ready(client, admin, app, fake, tmp_path, "t12@example.com", companies=2)
    second = client.post(
        f"/api/v1/workspaces/{tenant}/companies",
        json={"name": "Бета", "kind": "company"},
    )
    assert second.status_code == 200, second.text
    activated = client.post(f"/api/v1/billing/companies/{second.json()['id']}/activate")
    assert activated.status_code == 200, activated.text
    _wallet(client, first, "cash", "10000.00")
    _plan(client, first, "80000.00")
    _link(client, app, MORNING, user_id=505)
    _schedule(app, MORNING)
    text_value = _rows(admin, "SELECT payload->>'text' FROM notification_outbox")[0][0]
    assert "Альфа" in text_value
    assert "Бета" in text_value
    assert "неполный агрегат" in text_value
    assert "дефицит" in text_value


def test_urgent_resend_needs_twenty_percent(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "urgent@example.com")
    _wallet(client, company_id, "cash", "100000.00")
    _plan(client, company_id, "150000.00")
    _link(client, app, MORNING, user_id=506)
    _schedule(app, MORNING)
    _dispatch(app, MockTelegram(), MORNING)
    _plan(client, company_id, "20000.00")
    session = app.state.worker_session_factory()
    try:
        created = consider_urgent(session, app.state.settings, MORNING + timedelta(hours=7))
        session.commit()
    finally:
        session.close()
    assert created == 1
    session = app.state.worker_session_factory()
    try:
        again = consider_urgent(session, app.state.settings, MORNING + timedelta(hours=8))
        session.commit()
    finally:
        session.close()
    assert again == 0
    urgent = _rows(admin, "SELECT count(*) FROM notification_outbox WHERE alert_id IS NOT NULL")
    assert urgent[0][0] == 1


def test_operator_cannot_add_and_foreign_confirm_is_hidden(
    client, admin, app, fake, tmp_path
) -> None:
    tenant, company_id = _ready(client, admin, app, fake, tmp_path, "owner-tg@example.com")
    _wallet(client, company_id, "cash", "1000.00")
    invited = client.post(
        f"/api/v1/workspaces/{tenant}/invitations",
        json={"email": "op-tg@example.com", "role": "operator"},
    )
    assert invited.status_code == 200, invited.text
    with admin.connect() as connection:
        invite_link = connection.execute(
            text(
                "SELECT payload_redacted->>'link' FROM transactional_email_outbox "
                "WHERE type = 'invite' ORDER BY created_at DESC LIMIT 1"
            )
        ).scalar_one()
    token = token_from_link(str(invite_link))
    guest = TestClient(app)
    _verified_user(guest, admin, "op-tg@example.com", "Оператор")
    logged = login(guest, "op-tg@example.com")
    assert guest.post("/api/v1/auth/invitations/accept", json={"token": token}).status_code == 200
    guest.headers["X-Tenant-Id"] = tenant
    granted = client.post(
        f"/api/v1/workspaces/{tenant}/company-access",
        json={"user_id": logged["user"]["id"], "company_id": company_id},
    )
    assert granted.status_code == 200, granted.text
    guest_token = guest.post("/api/v1/telegram/link-token")
    assert guest_token.status_code == 200, guest_token.text
    _ingest(app, _message(70, f"/start {guest_token.json()['token']}", 507), MORNING)
    assert guest.post("/api/v1/telegram/binding/confirm").status_code == 200
    denied = _ingest(app, _message(71, "/add", 507), MORNING)
    assert "Недостаточно прав" in denied[0]["text"]
    assert client.post("/api/v1/telegram/binding/confirm").status_code == 404
    stranger = TestClient(app)
    _verified_user(stranger, admin, "other-tg@example.com", "Чужой")
    login(stranger, "other-tg@example.com")
    open_workspace(stranger, "Чужое")
    assert stranger.post("/api/v1/telegram/binding/confirm").status_code == 404


def test_webhook_is_disabled_without_secret(client) -> None:
    hidden = client.post("/api/v1/integrations/telegram/webhook", json={"update_id": 1})
    assert hidden.status_code == 404


def _verified_user(client, admin, email: str, name: str) -> None:
    created = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "name": name},
    )
    assert created.status_code == 200, created.text
    with admin.connect() as connection:
        link = connection.execute(
            text(
                "SELECT payload_redacted->>'link' FROM transactional_email_outbox "
                "WHERE type = 'verify_email' AND to_email = :email"
            ),
            {"email": email},
        ).scalar_one()
    verified = client.post(
        "/api/v1/auth/verify-email",
        json={"token": token_from_link(str(link))},
    )
    assert verified.status_code == 200, verified.text


def _add(app, wallet_label: str, amount: str, start: int) -> None:
    added = _ingest(app, _message(start, "/add"), MORNING)
    direction = _button(added, "Расход")
    wallets = _ingest(app, _click(start + 1, direction), MORNING)
    wallet = _button(wallets, wallet_label)
    _ingest(app, _click(start + 2, wallet), MORNING)
    _ingest(app, _message(start + 3, amount), MORNING)
    _ingest(app, _message(start + 4, "2026-10-14"), MORNING)
    _ingest(app, _message(start + 5, "без категории"), MORNING)
    _ingest(app, _message(start + 6, "пропустить"), MORNING)
    preview = _ingest(app, _message(start + 7, "пропустить"), MORNING)
    assert "не банковский платёж" in preview[0]["text"]
    confirm = _button(preview, "Подтвердить")
    _ingest(app, _click(start + 8, confirm), MORNING)
    _ingest(app, _click(start + 9, confirm), MORNING)


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


def _dispatch(app, transport: MockTelegram, at: datetime) -> int:
    session = app.state.worker_session_factory()
    try:
        handled = dispatch_outbox(session, app.state.settings, transport, at)
        session.commit()
        return handled
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _money_rows(rows: list) -> list[tuple[str, str, str]]:
    return [(status, source, f"{amount:.2f}") for status, source, amount in rows]
