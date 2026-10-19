from pathlib import Path

from alembic import op
from schema_sql import iter_statements

revision = "20261019_0013"
down_revision = "20261019_0012"
branch_labels = None
depends_on = None

_SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _run_sql(name: str) -> None:
    sql_path = _SQL_DIR / name
    for statement in iter_statements(sql_path.read_text(encoding="utf-8")):
        op.execute(statement)


def upgrade() -> None:
    _run_sql("0013_source_revision_unpost.sql")


def downgrade() -> None:
    _run_sql("0013_source_revision_unpost_downgrade.sql")
