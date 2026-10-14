from pathlib import Path

from alembic import op
from schema_sql import iter_statements

revision = "20261014_0005"
down_revision = "20261014_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "0005_revenue.sql"
    for statement in iter_statements(sql_path.read_text(encoding="utf-8")):
        op.execute(statement)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE source_identities DROP CONSTRAINT IF EXISTS source_identities_target_ck"
    )
    op.execute(
        "ALTER TABLE source_identities DROP CONSTRAINT IF EXISTS source_identities_revenue_fk"
    )
    op.execute("ALTER TABLE source_identities DROP COLUMN IF EXISTS revenue_entry_id")
    op.execute("DROP TABLE IF EXISTS revenue_cash_matches")
    op.execute("DROP TABLE IF EXISTS revenue_entries")
    op.execute("DROP TABLE IF EXISTS counterparties")
    op.execute("DROP TABLE IF EXISTS directions")
    op.execute(
        "ALTER TABLE source_connections "
        "DROP CONSTRAINT IF EXISTS source_connections_revenue_format_ck"
    )
    op.execute(
        "ALTER TABLE source_connections DROP CONSTRAINT IF EXISTS source_connections_vat_ck"
    )
    op.execute(
        "ALTER TABLE source_connections DROP CONSTRAINT IF EXISTS source_connections_dataset_ck"
    )
    op.execute("ALTER TABLE source_connections DROP COLUMN IF EXISTS vat_basis")
    op.execute("ALTER TABLE source_connections DROP COLUMN IF EXISTS coverage_through")
    op.execute("ALTER TABLE source_connections DROP COLUMN IF EXISTS dataset")
