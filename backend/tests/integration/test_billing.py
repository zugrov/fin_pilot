import threading
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.jobs.finance import dispatch_outbox, enqueue_financial_notice
from app.services.billing_service import apply_remote_payment, enqueue_renewal_reminders
from sqlalchemy import text
from tests.integration.conftest import (
    freeze,
    login,
    open_workspace,
    pay,
    process_payments,
    reconcile,
    register_and_verify,
)


def _ready(client, admin, app, email="owner@example.com"):
    freeze(app, datetime(2026, 10, 14, 9, tzinfo=UTC))
    register_and_verify(client, admin, email)
    login(client, email)
    open_workspace(client)
    return client


def _count(admin, table: str) -> int:
    with admin.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def test_pay2_pay3_pay6_server_price_and_return_do_not_grant(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    quoted = client.post(
        "/api/v1/billing/quote",
        json={
            "companies": 2,
            "interval": "month",
            "payable_amount": "1.00",
            "discount_percent": "99",
        },
    )
    assert quoted.status_code == 200
    assert quoted.json()["payable_amount"] == "4000.00"
    checked = client.post(
        "/api/v1/billing/checkout",
        json={"quote_id": quoted.json()["id"], "offer_accepted": True},
        headers={"Idempotency-Key": "pay2"},
    )
    assert checked.status_code == 200
    assert checked.json()["activated"] is False
    assert checked.json()["payable_amount"] == "4000.00"
    payment = client.get(f"/api/v1/billing/payments/{checked.json()['payment_id']}")
    assert payment.json()["activated"] is False
    assert _count(admin, "billing_activations") == 0
    provider_id = next(reversed(fake.by_id))
    fake.mark(provider_id, "pending")
    client.post(
        "/api/v1/integrations/yookassa/webhook",
        json={"event": "payment.waiting_for_capture", "object": {"id": provider_id}},
    )
    process_payments(app, fake)
    assert _count(admin, "billing_activations") == 0
    fake.mark(provider_id, "canceled")
    client.post(
        "/api/v1/integrations/yookassa/webhook",
        json={"event": "payment.canceled", "object": {"id": provider_id}},
    )
    process_payments(app, fake)
    assert _count(admin, "billing_activations") == 0
    fake.mark(provider_id, "succeeded")
    client.post(
        "/api/v1/integrations/yookassa/webhook",
        json={"event": "payment.succeeded", "object": {"id": provider_id}},
    )
    client.post(
        "/api/v1/integrations/yookassa/webhook",
        json={"event": "payment.succeeded", "object": {"id": provider_id}},
    )
    process_payments(app, fake)
    assert _count(admin, "billing_activations") == 1
    activated = client.get(f"/api/v1/billing/payments/{checked.json()['payment_id']}")
    assert activated.json()["activated"] is True


def test_pay5_rejects_mismatched_provider_payment(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    client.post("/api/v1/billing/quote", json={"companies": 1, "interval": "month"})
    quoted = client.post("/api/v1/billing/quote", json={"companies": 1, "interval": "month"})
    checked = client.post(
        "/api/v1/billing/checkout",
        json={"quote_id": quoted.json()["id"], "offer_accepted": True},
        headers={"Idempotency-Key": "pay5"},
    )
    assert checked.status_code == 200
    provider_id = next(reversed(fake.by_id))
    fake.mark(provider_id, "succeeded", amount={"value": "1.00", "currency": "RUB"})
    client.post(
        "/api/v1/integrations/yookassa/webhook",
        json={"event": "payment.succeeded", "object": {"id": provider_id}},
    )
    process_payments(app, fake)
    assert _count(admin, "billing_activations") == 0
    with admin.connect() as connection:
        status = connection.execute(text("SELECT status FROM invoices")).scalar_one()
    assert status == "manual_review"


def test_pay7_timeout_reuses_idempotence_key(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    quoted = client.post("/api/v1/billing/quote", json={"companies": 1, "interval": "month"})
    fake.timeout_once = True
    first = client.post(
        "/api/v1/billing/checkout",
        json={"quote_id": quoted.json()["id"], "offer_accepted": True},
        headers={"Idempotency-Key": "same-key"},
    )
    assert first.status_code == 202
    second = client.post(
        "/api/v1/billing/checkout",
        json={"quote_id": quoted.json()["id"], "offer_accepted": True},
        headers={"Idempotency-Key": "same-key"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["payment_id"] == first.json()["payment_id"]
    assert len(fake.by_id) == 1
    assert _count(admin, "payment_attempts") == 1


def test_pay8_pay10_pay11_period_changes(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    pay(client, app, fake, 1, "month")
    company = client.post(
        f"/api/v1/workspaces/{client.headers['X-Tenant-Id']}/companies",
        json={"name": "Альфа", "kind": "company"},
    )
    assert company.status_code == 200
    activated = client.post(f"/api/v1/billing/companies/{company.json()['id']}/activate")
    assert activated.status_code == 200
    before = client.get("/api/v1/billing/subscription").json()
    early = datetime.fromisoformat(before["paid_through"]) - timedelta(days=5)
    freeze(app, early)
    login(client, "owner@example.com")
    pay(client, app, fake, 1, "month")
    after = client.get("/api/v1/billing/subscription").json()
    assert after["current_period"]["end_at"] == before["paid_through"]
    assert after["paid_through"] > before["paid_through"]
    freeze(app, datetime.fromisoformat(before["current_period"]["start_at"]) + timedelta(days=1))
    upgraded = client.post("/api/v1/billing/quote", json={"companies": 2, "interval": "month"})
    assert Decimal(upgraded.json()["payable_amount"]) > 0
    pay_quote(client, app, fake, upgraded.json()["id"])
    upgraded_view = client.get("/api/v1/billing/subscription").json()
    assert upgraded_view["current_period"]["end_at"] == before["current_period"]["end_at"]
    assert upgraded_view["company_limit"] == 2
    scheduled = client.post(
        "/api/v1/billing/subscription/schedule-change",
        json={"companies": 1, "keep_company_ids": [company.json()["id"]]},
    )
    assert scheduled.status_code == 200
    assert scheduled.json()["scheduled_company_limit"] == 1
    assert scheduled.json()["company_limit"] == 2
    assert _count(admin, "refunds") == 0


def pay_quote(client, app, fake, quote_id: str) -> None:
    checked = client.post(
        "/api/v1/billing/checkout",
        json={"quote_id": quote_id, "offer_accepted": True},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert checked.status_code == 200, checked.text
    provider_id = next(reversed(fake.by_id))
    fake.mark(provider_id, "succeeded")
    client.post(
        "/api/v1/integrations/yookassa/webhook",
        json={"event": "payment.succeeded", "object": {"id": provider_id}},
    )
    process_payments(app, fake)


def test_pay9_second_company_without_slot_is_blocked(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    pay(client, app, fake, 1, "month")
    tenant = client.headers["X-Tenant-Id"]
    first = client.post(
        f"/api/v1/workspaces/{tenant}/companies",
        json={"name": "Один", "kind": "company"},
    )
    second = client.post(
        f"/api/v1/workspaces/{tenant}/companies",
        json={"name": "Два", "kind": "company"},
    )
    opened = client.post(f"/api/v1/billing/companies/{first.json()['id']}/activate")
    assert opened.status_code == 200
    blocked = client.post(f"/api/v1/billing/companies/{second.json()['id']}/activate")
    assert blocked.status_code == 402


def test_pay12_pay13_expiry_blocks_finance_not_login(client, admin, app, fake) -> None:
    _ready(client, admin, app, email="later@example.com")
    pay(client, app, fake, 1, "month")
    tenant = client.headers["X-Tenant-Id"]
    company = client.post(
        f"/api/v1/workspaces/{tenant}/companies",
        json={"name": "Фирма", "kind": "company"},
    ).json()
    assert client.post(f"/api/v1/billing/companies/{company['id']}/activate").status_code == 200
    session = app.state.worker_session_factory()
    try:
        from sqlalchemy import text as sql_text

        user_id = session.execute(
            sql_text("SELECT id FROM users WHERE normalized_email = 'later@example.com'")
        ).scalar_one()
        from app.models.identity import User

        user = session.get(User, user_id)
        enqueue_financial_notice(
            session,
            user=user,
            tenant_id=uuid.UUID(tenant),
            company_id=uuid.UUID(company["id"]),
            at=app.state.clock.now(),
            grace_days=3,
            bypass=False,
        )
        session.commit()
    finally:
        session.close()
    paid_raw = client.get("/api/v1/billing/subscription").json()["paid_through"]
    paid_through = datetime.fromisoformat(paid_raw)
    freeze(app, paid_through + timedelta(days=1))
    login(client, "later@example.com")
    assert client.get("/api/v1/auth/me").status_code == 200
    assert client.get("/api/v1/billing/tariff").status_code == 200
    denied = client.patch(
        f"/api/v1/companies/{company['id']}",
        json={"min_cash_reserve": "10.00"},
    )
    assert denied.status_code == 402
    sender = app.state.worker_session_factory()
    try:
        from app.integrations.email import MockEmailProvider

        mailbox = MockEmailProvider()
        dispatch_outbox(sender, app.state.settings, mailbox, app.state.clock.now())
        sender.commit()
        assert all(item.template_key != "digest" for item in mailbox.sent)
    finally:
        sender.close()
    with admin.connect() as connection:
        status = connection.execute(
            text("SELECT status FROM transactional_email_outbox WHERE category = 'financial'")
        ).scalar_one()
    assert status == "cancelled"


def test_pay14_test_payment_does_not_activate_live_tenant(client, admin, app, fake) -> None:
    _ready(client, admin, app, email="live@example.com")
    quoted = client.post("/api/v1/billing/quote", json={"companies": 1, "interval": "month"})
    checked = client.post(
        "/api/v1/billing/checkout",
        json={"quote_id": quoted.json()["id"], "offer_accepted": True},
        headers={"Idempotency-Key": "pay14"},
    )
    assert checked.status_code == 200, checked.text
    with admin.begin() as connection:
        connection.execute(text("UPDATE tenants SET is_live = true"))
    provider_id = next(reversed(fake.by_id))
    fake.mark(provider_id, "succeeded")
    client.post(
        "/api/v1/integrations/yookassa/webhook",
        json={"event": "payment.succeeded", "object": {"id": provider_id}},
    )
    process_payments(app, fake)
    assert _count(admin, "billing_activations") == 0


def test_pay15_parallel_upgrade_does_not_double_limit(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    pay(client, app, fake, 1, "month")
    first = client.post("/api/v1/billing/quote", json={"companies": 2, "interval": "month"})
    second = client.post("/api/v1/billing/quote", json={"companies": 2, "interval": "month"})
    pay_quote(client, app, fake, first.json()["id"])
    checked = client.post(
        "/api/v1/billing/checkout",
        json={"quote_id": second.json()["id"], "offer_accepted": True},
        headers={"Idempotency-Key": "second-upgrade"},
    )
    assert checked.status_code in {200, 409}
    if checked.status_code == 200:
        provider_id = next(reversed(fake.by_id))
        fake.mark(provider_id, "succeeded")
        client.post(
            "/api/v1/integrations/yookassa/webhook",
            json={"event": "payment.succeeded", "object": {"id": provider_id}},
        )
        process_payments(app, fake)
    view = client.get("/api/v1/billing/subscription").json()
    assert view["company_limit"] == 2
    assert _count(admin, "billing_activations") == 2


def test_pay16_saas_payment_does_not_create_cash(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    pay(client, app, fake, 1, "month")
    from app.models import Base

    assert "cash_transactions" not in Base.metadata.tables
    assert _count(admin, "billing_activations") == 1


def test_pay17_no_default_vat_and_live_checkout_blocked(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    pay(client, app, fake, 1, "year")
    with admin.connect() as connection:
        rows = connection.execute(text("SELECT receipt_attributes FROM invoice_lines"))
        attributes = rows.scalars().all()
    assert attributes
    assert all("vat_rate" not in item for item in attributes)
    app.state.settings.billing_mode = "live"
    app.state.settings.receipt_mode = ""
    quoted = client.post("/api/v1/billing/quote", json={"companies": 1, "interval": "month"})
    blocked = client.post(
        "/api/v1/billing/checkout",
        json={"quote_id": quoted.json()["id"], "offer_accepted": True},
        headers={"Idempotency-Key": "live"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["code"] == "receipt_config_missing"
    tariff = client.get("/api/v1/billing/tariff").json()
    assert tariff["annual_offer_status"] == "approved"
    assert tariff["annual_discount_percent"] == "15.00"


def test_pay18_reconciliation_without_webhook(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    quoted = client.post("/api/v1/billing/quote", json={"companies": 1, "interval": "month"})
    checked = client.post(
        "/api/v1/billing/checkout",
        json={"quote_id": quoted.json()["id"], "offer_accepted": True},
        headers={"Idempotency-Key": "pay18"},
    )
    assert checked.status_code == 200
    provider_id = next(reversed(fake.by_id))
    fake.mark(provider_id, "succeeded")
    reconcile(app, fake)
    assert _count(admin, "billing_activations") == 1


def test_pay19_full_refund_revokes_access_and_keeps_company(client, admin, app, fake) -> None:
    _ready(client, admin, app, email="staff@seller.example")
    pay(client, app, fake, 1, "month")
    tenant = client.headers["X-Tenant-Id"]
    company = client.post(
        f"/api/v1/workspaces/{tenant}/companies",
        json={"name": "Останется", "kind": "company"},
    ).json()
    client.post(f"/api/v1/billing/companies/{company['id']}/activate")
    app.state.settings.refunds_enabled = True
    app.state.settings.billing_staff_emails = "staff@seller.example"
    with admin.connect() as connection:
        attempt_id = connection.execute(text("SELECT id FROM payment_attempts")).scalar_one()
        amount = connection.execute(text("SELECT amount FROM payment_attempts")).scalar_one()
    refunded = client.post(
        "/api/v1/billing/staff/refunds",
        json={
            "payment_attempt_id": str(attempt_id),
            "reason": "тест полного возврата",
            "remote": {
                "id": "refund-1",
                "status": "succeeded",
                "payment_id": "pay",
                "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
            },
        },
    )
    assert refunded.status_code == 200, refunded.text
    assert client.get(f"/api/v1/companies/{company['id']}").status_code == 200
    denied = client.get(f"/api/v1/companies/{company['id']}/dashboard")
    assert denied.status_code == 402
    assert _count(admin, "companies") == 1


def test_year3_year8_year9_interval_switch(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    pay(client, app, fake, 1, "month")
    view = client.get("/api/v1/billing/subscription").json()
    quoted = client.post(
        "/api/v1/billing/quote",
        json={"companies": 1, "interval": "year", "discount_percent": "0"},
    )
    assert quoted.status_code == 200
    assert quoted.json()["payable_amount"] == "25500.00"
    assert quoted.json()["period_start"] == view["paid_through"]
    pay_quote(client, app, fake, quoted.json()["id"])
    switched = client.post("/api/v1/billing/quote", json={"companies": 1, "interval": "month"})
    paid_through = client.get("/api/v1/billing/subscription").json()["paid_through"]
    assert switched.json()["period_start"] == paid_through
    current = client.get("/api/v1/billing/subscription").json()
    assert current["current_interval"] == "month"
    assert current["future_periods"][0]["interval"] == "year"


def test_year5_year6_upgrade_uses_paid_discount(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    pay(client, app, fake, 1, "year")
    period = client.get("/api/v1/billing/subscription").json()["current_period"]
    start = datetime.fromisoformat(period["start_at"])
    end = datetime.fromisoformat(period["end_at"])
    midpoint = start + (end - start) / 2
    freeze(app, midpoint)
    login(client, "owner@example.com")
    with admin.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO annual_offer_versions ("
                "id, tariff_version_id, discount_percent, status, approved_by, "
                "approved_at, approval_source, offer_terms_version, valid_from, created_at) "
                "VALUES ('00000000-0000-4000-8000-000000000099', "
                "'00000000-0000-4000-8000-000000000001', 0, 'approved', 'user', "
                "'2026-12-01T00:00:00Z', 'user', 'later', '2026-12-01T00:00:00Z', now())"
            )
        )
    quoted = client.post("/api/v1/billing/quote", json={"companies": 2, "interval": "year"})
    assert quoted.status_code == 200, quoted.text
    assert Decimal(quoted.json()["payable_amount"]) == Decimal("7650.00")
    with admin.connect() as connection:
        stored = connection.execute(
            text("SELECT discount_percent FROM billing_periods")
        ).scalar_one()
    assert stored == Decimal("15.000000") or stored == Decimal("15")


def test_year10_replay_does_not_overlap(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    pay(client, app, fake, 1, "year")
    provider_id = next(reversed(fake.by_id))
    client.post(
        "/api/v1/integrations/yookassa/webhook",
        json={"event": "payment.succeeded", "object": {"id": provider_id}},
    )
    process_payments(app, fake)
    assert _count(admin, "billing_periods") == 1
    assert _count(admin, "billing_activations") == 1


def test_year13_reminders_do_not_charge(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    pay(client, app, fake, 1, "year")
    calls = fake.calls
    paid_raw = client.get("/api/v1/billing/subscription").json()["paid_through"]
    freeze(app, datetime.fromisoformat(paid_raw) - timedelta(days=30))
    session = app.state.worker_session_factory()
    try:
        created = enqueue_renewal_reminders(session, app.state.settings, app.state.clock.now())
        session.commit()
    finally:
        session.close()
    assert created == 1
    assert fake.calls == calls
    assert _count(admin, "payment_attempts") == 1


def test_year14_access_until_paid_through(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    pay(client, app, fake, 1, "year")
    tenant = client.headers["X-Tenant-Id"]
    company = client.post(
        f"/api/v1/workspaces/{tenant}/companies",
        json={"name": "Год", "kind": "company"},
    ).json()
    client.post(f"/api/v1/billing/companies/{company['id']}/activate")
    end = datetime.fromisoformat(client.get("/api/v1/billing/subscription").json()["paid_through"])
    freeze(app, end - timedelta(days=40))
    login(client, "owner@example.com")
    assert client.get(f"/api/v1/companies/{company['id']}/dashboard").status_code == 200
    freeze(app, end + timedelta(seconds=1))
    login(client, "owner@example.com")
    assert client.patch(
        f"/api/v1/companies/{company['id']}",
        json={"min_cash_reserve": "1.00"},
    ).status_code == 402


def test_year16_year17_future_period_does_not_expand_current_scope(
    client, admin, app, fake
) -> None:
    _ready(client, admin, app)
    pay(client, app, fake, 1, "month")
    tenant = client.headers["X-Tenant-Id"]
    first = client.post(
        f"/api/v1/workspaces/{tenant}/companies",
        json={"name": "Первая", "kind": "company"},
    ).json()
    second = client.post(
        f"/api/v1/workspaces/{tenant}/companies",
        json={"name": "Вторая", "kind": "company"},
    ).json()
    assert client.post(f"/api/v1/billing/companies/{first['id']}/activate").status_code == 200
    quoted = client.post("/api/v1/billing/quote", json={"companies": 2, "interval": "year"})
    assert quoted.json()["payable_amount"] == "40800.00"
    pay_quote(client, app, fake, quoted.json()["id"])
    view = client.get("/api/v1/billing/subscription").json()
    assert view["company_limit"] == 1
    assert view["future_periods"][0]["company_limit"] == 2
    blocked = client.post(f"/api/v1/billing/companies/{second['id']}/activate")
    assert blocked.status_code == 402
    future_start = datetime.fromisoformat(view["future_periods"][0]["start_at"])
    freeze(app, future_start + timedelta(minutes=1))
    login(client, "owner@example.com")
    opened = client.post(f"/api/v1/billing/companies/{second['id']}/activate")
    assert opened.status_code == 200, opened.text


def test_spoofed_forwarded_header_is_ignored(client, app) -> None:
    app.state.settings.yookassa_ip_allowlist = "203.0.113.10"
    response = client.post(
        "/api/v1/integrations/yookassa/webhook",
        json={"event": "payment.succeeded", "object": {"id": "missing"}},
        headers={"X-Forwarded-For": "203.0.113.10"},
    )
    assert response.status_code == 403


def test_pay15_concurrent_activation_is_once(client, admin, app, fake) -> None:
    _ready(client, admin, app)
    pay(client, app, fake, 1, "month")
    quoted = client.post("/api/v1/billing/quote", json={"companies": 2, "interval": "month"})
    assert quoted.status_code == 200, quoted.text
    checked = client.post(
        "/api/v1/billing/checkout",
        json={"quote_id": quoted.json()["id"], "offer_accepted": True},
        headers={"Idempotency-Key": "pay15-race"},
    )
    assert checked.status_code == 200, checked.text
    provider_id = next(reversed(fake.by_id))
    remote = fake.mark(provider_id, "succeeded")
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def activate() -> None:
        session = app.state.worker_session_factory()
        try:
            barrier.wait(timeout=5)
            apply_remote_payment(session, app.state.settings, remote, app.state.clock.now())
            session.commit()
        except BaseException as exc:
            session.rollback()
            errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=activate) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert errors == [], errors
    assert all(not thread.is_alive() for thread in threads)
    assert _count(admin, "billing_activations") == 2
    assert client.get("/api/v1/billing/subscription").json()["company_limit"] == 2

