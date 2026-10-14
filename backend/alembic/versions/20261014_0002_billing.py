from pathlib import Path

from alembic import op
from schema_sql import iter_statements

revision = "20261014_0002"
down_revision = "20261014_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "0002_billing.sql"
    for statement in iter_statements(sql_path.read_text(encoding="utf-8")):
        op.execute(statement)


def downgrade() -> None:
    op.execute(
        "DROP TABLE IF EXISTS billing_audit, refunds, billing_activations, "
        "billing_webhook_inbox, payment_attempts, invoice_lines, invoices, billing_quotes, "
        "company_entitlements, billing_periods, subscriptions, billing_accounts, "
        "annual_offer_versions, tariff_versions CASCADE"
    )
    op.execute("DROP FUNCTION IF EXISTS app_subscriptions_for_reminders()")
    op.execute("DROP FUNCTION IF EXISTS app_mark_outbox(uuid, text, text)")
    op.execute("DROP FUNCTION IF EXISTS app_pending_outbox()")
    op.execute("DROP FUNCTION IF EXISTS app_open_payments()")
    op.execute("DROP FUNCTION IF EXISTS app_payment_context(text)")
    op.execute("DROP FUNCTION IF EXISTS forbid_period_snapshot_change()")
    op.execute("DROP FUNCTION IF EXISTS forbid_invoice_price_change()")
    op.execute("DROP FUNCTION IF EXISTS forbid_row_mutation()")
    op.execute("DROP SEQUENCE IF EXISTS invoice_number_seq")
