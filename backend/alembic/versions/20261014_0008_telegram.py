from pathlib import Path

from alembic import op
from schema_sql import iter_statements

revision = "20261014_0008"
down_revision = "20261014_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    sql_path = Path(__file__).resolve().parents[1] / "sql" / "0008_telegram.sql"
    for statement in iter_statements(sql_path.read_text(encoding="utf-8")):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_claim_notification_outbox(timestamptz, integer)")
    op.execute("DROP FUNCTION IF EXISTS app_expire_notification_leases(timestamptz)")
    op.execute("DROP FUNCTION IF EXISTS app_list_digest_subscriptions()")
    op.execute("DROP FUNCTION IF EXISTS app_finish_telegram_update(uuid, text, uuid)")
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "app_record_telegram_update(uuid, text, bigint, text, jsonb, timestamptz)"
    )
    op.execute("DROP FUNCTION IF EXISTS app_binding_by_telegram(bigint)")
    op.execute("DROP FUNCTION IF EXISTS app_consume_link_token(text, timestamptz)")
    op.execute("DROP TABLE IF EXISTS bot_drafts")
    op.execute("DROP TABLE IF EXISTS telegram_updates")
    op.execute("DROP TABLE IF EXISTS notification_outbox")
    op.execute("DROP TABLE IF EXISTS digest_snapshots")
    op.execute("DROP TABLE IF EXISTS digest_subscriptions")
    op.execute("DROP TABLE IF EXISTS telegram_bindings")
    op.execute("DROP TABLE IF EXISTS telegram_link_tokens")
