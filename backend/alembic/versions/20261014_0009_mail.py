from pathlib import Path

from alembic import op
from schema_sql import iter_statements

revision = "20261014_0009"
down_revision = "20261014_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "0009_mail.sql"
    for statement in iter_statements(sql_path.read_text(encoding="utf-8")):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_list_email_sources(timestamptz)")
    op.execute("DROP TABLE IF EXISTS email_ingestions")
    op.execute("ALTER TABLE source_connections DROP CONSTRAINT IF EXISTS source_connections_poll_ck")
    op.execute("ALTER TABLE source_connections DROP COLUMN IF EXISTS last_error")
    op.execute("ALTER TABLE source_connections DROP COLUMN IF EXISTS encrypted_credentials")
    op.execute("ALTER TABLE source_connections DROP COLUMN IF EXISTS config_redacted")
    op.execute("ALTER TABLE source_connections DROP COLUMN IF EXISTS next_attempt_at")
    op.execute("ALTER TABLE source_connections DROP COLUMN IF EXISTS last_success_at")
    op.execute("ALTER TABLE source_connections DROP COLUMN IF EXISTS last_attempt_at")
    op.execute("ALTER TABLE source_connections DROP COLUMN IF EXISTS poll_interval_minutes")
    op.execute("ALTER TABLE source_connections DROP CONSTRAINT IF EXISTS source_connections_type_ck")
    op.execute(
        "ALTER TABLE source_connections ADD CONSTRAINT source_connections_type_ck "
        "CHECK (type IN ('file', 'clientbank', 'onec'))"
    )
