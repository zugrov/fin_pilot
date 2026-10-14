from pathlib import Path

from alembic import op
from schema_sql import iter_statements

revision = "20261014_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "0001_identity.sql"
    for statement in iter_statements(sql_path.read_text(encoding="utf-8")):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_records, invitations, company_access, companies, memberships, tenants, audit_log, transactional_email_outbox, verification_tokens, sessions, users CASCADE")
    op.execute("DROP FUNCTION IF EXISTS app_invitation_context(text)")
    op.execute("DROP FUNCTION IF EXISTS app_user()")
    op.execute("DROP FUNCTION IF EXISTS app_tenant()")
