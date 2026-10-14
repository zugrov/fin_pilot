from pathlib import Path

from alembic import op
from schema_sql import iter_statements

revision = "20261014_0004"
down_revision = "20261014_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "0004_import.sql"
    for statement in iter_statements(sql_path.read_text(encoding="utf-8")):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS classification_rules CASCADE")
    op.execute("DROP TABLE IF EXISTS source_identities CASCADE")
    op.execute("DROP TABLE IF EXISTS raw_import_rows CASCADE")
    op.execute("DROP TABLE IF EXISTS import_batches CASCADE")
    op.execute("DROP TABLE IF EXISTS import_profiles CASCADE")
    op.execute("DROP TABLE IF EXISTS source_connections CASCADE")
    op.execute("DROP INDEX IF EXISTS cash_transactions_match")
    op.execute("ALTER TABLE cash_transactions DROP COLUMN IF EXISTS counterparty_name")
    op.execute("ALTER TABLE cash_transactions DROP COLUMN IF EXISTS counterparty_inn")
    op.execute("DROP INDEX IF EXISTS uq_wallets_code")
    op.execute("ALTER TABLE wallets DROP COLUMN IF EXISTS code")
