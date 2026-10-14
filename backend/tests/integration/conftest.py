import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

os.environ["APP_ENV"] = "test"
_PORT = os.environ.get("TEST_PG_PORT", "5432")
os.environ["DATABASE_URL"] = (
    f"postgresql+psycopg://finpilot_app:finpilot_test_only@127.0.0.1:{_PORT}/finpilot_test"
)
os.environ["WORKER_DATABASE_URL"] = (
    f"postgresql+psycopg://finpilot_worker:finpilot_test_only@127.0.0.1:{_PORT}/finpilot_test"
)
os.environ["MIGRATION_DATABASE_URL"] = f"postgresql+psycopg://127.0.0.1:{_PORT}/finpilot_test"
os.environ["SESSION_COOKIE_SECURE"] = "false"
os.environ["EMAIL_PROVIDER_MODE"] = "mock"
os.environ["SEND_REAL_EMAIL"] = "false"
os.environ["SEND_LIVE_PAYMENTS"] = "false"
os.environ["SEND_EXTERNAL_MESSAGES"] = "false"
os.environ["BILLING_MODE"] = "test"
os.environ["RATE_LIMIT_BACKEND"] = "memory"
os.environ["YOOKASSA_SHOP_ID"] = "shop-test"
os.environ["PUBLIC_BASE_URL"] = "http://localhost:5173"
os.environ["ANNUAL_BILLING_ENABLED"] = "true"
os.environ["REFUNDS_ENABLED"] = "false"

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from app.clock import FixedClock, SystemClock
from app.config import Settings
from app.integrations.payments import FakeYooKassa
from app.main import create_app
from app.services.billing_service import process_inbox, reconcile_open_payments
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[2]
PASSWORD = "long-password-1"
TRUNCATE = """
revenue_cash_matches, source_identities, raw_import_rows, import_batches, import_profiles,
revenue_entries, counterparties, directions,
classification_rules, source_connections,
transaction_revisions, cash_transactions, transfer_groups, opening_balances,
wallet_access, wallets, cash_categories,
billing_audit, refunds, billing_activations, billing_webhook_inbox,
payment_attempts, invoice_lines, invoices, billing_quotes, company_entitlements,
billing_periods, subscriptions, billing_accounts, idempotency_records, invitations,
company_access, companies, memberships, tenants, audit_log, transactional_email_outbox,
verification_tokens, sessions, users
"""


def _admin():
    return psycopg.connect(f"postgresql://127.0.0.1:{_PORT}/postgres", autocommit=True)


@pytest.fixture(scope="session")
def migrated_database():
    admin = _admin()
    exists = admin.execute(
        "SELECT 1 FROM pg_database WHERE datname = 'finpilot_test'"
    ).fetchone()
    if exists is None:
        admin.execute("CREATE DATABASE finpilot_test")
    config = Config(str(BACKEND / "alembic.ini"))
    previous = os.getcwd()
    os.chdir(BACKEND)
    try:
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        command.upgrade(config, "head")
    finally:
        os.chdir(previous)
    admin.execute("ALTER ROLE finpilot_app WITH LOGIN PASSWORD 'finpilot_test_only'")
    admin.execute("ALTER ROLE finpilot_worker WITH LOGIN PASSWORD 'finpilot_test_only'")
    admin.execute("GRANT CONNECT ON DATABASE finpilot_test TO finpilot_app, finpilot_worker")
    admin.close()
    engine = create_engine(os.environ["MIGRATION_DATABASE_URL"])
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(migrated_database):
    yield
    with migrated_database.begin() as connection:
        connection.execute(text(f"TRUNCATE {TRUNCATE} RESTART IDENTITY CASCADE"))


@pytest.fixture
def app(migrated_database):
    application = create_app(Settings())
    application.state.clock = SystemClock()
    yield application
    application.state.engine.dispose()
    application.state.worker_engine.dispose()


@pytest.fixture
def fake() -> FakeYooKassa:
    return FakeYooKassa(shop_id="shop-test")


@pytest.fixture
def client(app, fake) -> Iterator[TestClient]:
    app.state.payment_provider_factory = lambda: fake
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin(migrated_database):
    return migrated_database


def latest_link(admin) -> str:
    with admin.connect() as connection:
        link = connection.execute(
            text(
                "SELECT payload_redacted->>'link' FROM transactional_email_outbox "
                "WHERE payload_redacted ? 'link' ORDER BY created_at DESC LIMIT 1"
            )
        ).scalar_one()
    return str(link)


def token_from_link(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


def register_and_verify(client: TestClient, admin, email: str, name: str = "Ольга") -> None:
    created = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "name": name},
    )
    assert created.status_code == 200
    client.post(
        "/api/v1/auth/verify-email",
        json={"token": token_from_link(latest_link(admin))},
    )


def login(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return response.json()


def open_workspace(client: TestClient, name: str = "Рабочее пространство") -> str:
    response = client.post("/api/v1/workspaces", json={"name": name})
    assert response.status_code == 200, response.text
    tenant_id = response.json()["id"]
    client.headers["X-Tenant-Id"] = tenant_id
    return tenant_id


def freeze(app, moment: datetime) -> None:
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    app.state.clock = FixedClock(moment)


def process_payments(app, fake: FakeYooKassa) -> None:
    session = app.state.worker_session_factory()
    try:
        process_inbox(session, fake, app.state.settings, app.state.clock.now())
        session.commit()
    finally:
        session.close()


def reconcile(app, fake: FakeYooKassa) -> None:
    session = app.state.worker_session_factory()
    try:
        reconcile_open_payments(session, fake, app.state.settings, app.state.clock.now())
        session.commit()
    finally:
        session.close()


def pay(client: TestClient, app, fake: FakeYooKassa, companies: int, interval: str) -> dict:
    quoted = client.post(
        "/api/v1/billing/quote",
        json={"companies": companies, "interval": interval, "payable_amount": "1.00"},
    )
    assert quoted.status_code == 200, quoted.text
    quote = quoted.json()
    checked = client.post(
        "/api/v1/billing/checkout",
        json={"quote_id": quote["id"], "offer_accepted": True, "discount_percent": "0"},
        headers={"Idempotency-Key": os.urandom(8).hex()},
    )
    assert checked.status_code == 200, checked.text
    provider_id = next(reversed(fake.by_id))
    fake.mark(provider_id, "succeeded")
    webhook = client.post(
        "/api/v1/integrations/yookassa/webhook",
        json={"event": "payment.succeeded", "object": {"id": provider_id}},
    )
    assert webhook.status_code == 200
    process_payments(app, fake)
    return quote
