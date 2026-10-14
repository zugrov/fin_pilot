from pathlib import Path

from alembic import op
from schema_sql import iter_statements

revision = "20261014_0003"
down_revision = "20261014_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "0003_cash.sql"
    for statement in iter_statements(sql_path.read_text(encoding="utf-8")):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS cash_transactions_posted_guard ON cash_transactions")
    op.execute("DROP TABLE IF EXISTS transaction_revisions, cash_transactions CASCADE")
    op.execute(
        "DROP TABLE IF EXISTS transfer_groups, opening_balances, wallet_access, "
        "wallets, cash_categories CASCADE"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_posted_cash_change()")
    op.execute("DROP FUNCTION IF EXISTS seed_cash_categories(uuid)")
    op.execute("ALTER TABLE companies DROP CONSTRAINT IF EXISTS companies_tenant_id_uq")
    op.execute("GRANT UPDATE ON billing_webhook_inbox TO finpilot_app")
    op.execute("GRANT INSERT ON billing_webhook_inbox TO finpilot_worker")
