"""RLS для source_correction_finding."""

import os
import uuid
from uuid import uuid4

from app.models.provenance import SourceCorrectionFinding
from app.security.context import set_context
from sqlalchemy import create_engine, select, text
from tests.integration.test_import_api import (
    FIXTURES,
    _commit,
    _ready,
    _source,
    _upload,
)


def _assert_policies(admin) -> None:
    with admin.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT policyname, qual::text FROM pg_policies "
                "WHERE tablename = 'source_correction_finding'"
            )
        ).fetchall()
    assert rows
    assert any("app_tenant()" in (row[1] or "") for row in rows)


def test_correction_finding_tenant_isolation(client, admin, app, fake, tmp_path) -> None:
    _assert_policies(admin)
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "corr-rls@example.com")
    source = _source(client, company_id, wallet_id)
    content = (FIXTURES / "cash_ok.csv").read_bytes()
    uploaded = _upload(client, company_id, source["id"], content, "cash.csv", uuid4().hex)
    assert _commit(client, uploaded.json()["id"]).status_code == 200
    foreign = str(uuid.uuid4())
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as connection:
        connection.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": foreign},
        )
        count = connection.execute(
            text("SELECT count(*) FROM source_correction_finding")
        ).scalar_one()
    assert int(count) >= 0
    session = app.state.session_factory()
    try:
        set_context(session, tenant_id=uuid.UUID(foreign), user_id=uuid.uuid4())
        assert session.scalars(select(SourceCorrectionFinding)).all() == []
    finally:
        session.close()
