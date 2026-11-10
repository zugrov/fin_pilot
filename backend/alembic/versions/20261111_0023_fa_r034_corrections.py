from pathlib import Path

from alembic import op
from schema_sql import iter_statements

revision = "20261111_0023"
down_revision = "20261110_0022"
branch_labels = None
depends_on = None

_SQL_DIR = Path(__file__).resolve().parents[1] / "sql"


def _run_sql(name: str) -> None:
    sql_path = _SQL_DIR / name
    for statement in iter_statements(sql_path.read_text(encoding="utf-8")):
        op.execute(statement)


def upgrade() -> None:
    _run_sql("0023_fa_r034_corrections.sql")


def downgrade() -> None:
    _run_sql("0023_fa_r034_corrections_downgrade.sql")
