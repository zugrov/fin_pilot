from pathlib import Path

from alembic import op
from schema_sql import iter_statements

revision = "20261014_0007"
down_revision = "20261014_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "0007_signals.sql"
    for statement in iter_statements(sql_path.read_text(encoding="utf-8")):
        op.execute(statement)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE source_identities DROP CONSTRAINT IF EXISTS source_identities_target_ck"
    )
    op.execute(
        "ALTER TABLE source_identities DROP CONSTRAINT IF EXISTS source_identities_budget_fk"
    )
    op.execute("ALTER TABLE source_identities DROP COLUMN IF EXISTS budget_line_id")
    op.execute(
        """
        ALTER TABLE source_identities ADD CONSTRAINT source_identities_target_ck CHECK (
          (
            entity_type = 'cash_transaction'
            AND canonical_entity_id IS NOT NULL
            AND revenue_entry_id IS NULL
            AND planned_event_id IS NULL
          )
          OR (
            entity_type = 'revenue_entry'
            AND revenue_entry_id IS NOT NULL
            AND canonical_entity_id IS NULL
            AND planned_event_id IS NULL
          )
          OR (
            entity_type = 'planned_event'
            AND planned_event_id IS NOT NULL
            AND canonical_entity_id IS NULL
            AND revenue_entry_id IS NULL
          )
        )
        """
    )
    op.execute(
        "ALTER TABLE source_connections DROP CONSTRAINT IF EXISTS source_connections_dataset_ck"
    )
    op.execute(
        "ALTER TABLE source_connections ADD CONSTRAINT source_connections_dataset_ck "
        "CHECK (dataset IN ('cash', 'revenue', 'plan'))"
    )
    op.execute("DROP TABLE IF EXISTS alerts")
    op.execute("DROP TABLE IF EXISTS alert_rules")
    op.execute("DROP TABLE IF EXISTS budget_daily_allocations")
    op.execute("DROP TABLE IF EXISTS budget_lines")
    op.execute("DROP TABLE IF EXISTS budget_versions")
