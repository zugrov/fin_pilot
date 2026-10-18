from __future__ import annotations

import os
from pathlib import Path

import psycopg
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

BACKEND = Path(__file__).resolve().parents[2]

TRUNCATE = """
email_ingestions,
notification_outbox, bot_drafts, digest_snapshots, digest_subscriptions,
telegram_updates, telegram_bindings, telegram_link_tokens,
alerts, alert_rules, budget_daily_allocations, budget_lines, budget_versions,
forecast_contributions, forecast_points, forecast_runs, obligation_cash_links,
payment_matches, planned_cash_events, obligations, recurrence_rules,
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


def admin_connect(port: str):
    return psycopg.connect(f"postgresql://127.0.0.1:{port}/postgres", autocommit=True)


def ensure_database_and_roles(port: str) -> None:
    admin = admin_connect(port)
    exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = 'finpilot_test'").fetchone()
    if exists is None:
        admin.execute("CREATE DATABASE finpilot_test")
    config = Config(str(BACKEND / "alembic.ini"))
    previous = os.getcwd()
    os.chdir(BACKEND)
    try:
        # E2E: только head + truncate; downgrade/base ломается при balances sources в данных.
        command.upgrade(config, "head")
    finally:
        os.chdir(previous)
    admin.execute("ALTER ROLE finpilot_app WITH LOGIN PASSWORD 'finpilot_test_only'")
    admin.execute("ALTER ROLE finpilot_worker WITH LOGIN PASSWORD 'finpilot_test_only'")
    admin.execute("GRANT CONNECT ON DATABASE finpilot_test TO finpilot_app, finpilot_worker")
    admin.close()


def truncate_all(port: str) -> None:
    url = f"postgresql+psycopg://127.0.0.1:{port}/finpilot_test"
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {TRUNCATE} RESTART IDENTITY CASCADE"))
    engine.dispose()
