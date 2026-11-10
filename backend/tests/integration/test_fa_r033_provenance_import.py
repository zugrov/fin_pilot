import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from tests.integration.conftest import freeze
from tests.integration.test_import_api import (
    FIXTURES,
    _commit,
    _ready,
    _source,
    _upload,
)
from tests.synthetic_polygon.constants import polygon_frozen_moment

_REV_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"


@pytest.fixture(autouse=True)
def _frozen_import_clock(app) -> None:
    if os.environ.get("TEST_FIXED_CLOCK_ISO", "").strip():
        return
    freeze(app, polygon_frozen_moment())


def test_commit_writes_fingerprint_and_lineage(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "prov@example.com")
    source = _source(client, company_id, wallet_id)
    content = (FIXTURES / "cash_ok.csv").read_bytes()
    uploaded = _upload(client, company_id, source["id"], content, "cash.csv", uuid4().hex)
    assert uploaded.status_code == 200, uploaded.text
    batch_id = uploaded.json()["id"]
    committed = _commit(client, batch_id)
    assert committed.status_code == 200, committed.text
    with admin.connect() as connection:
        fp_count = connection.execute(
            text("SELECT count(*) FROM import_source_fingerprints WHERE import_batch_id = :b"),
            {"b": batch_id},
        ).scalar_one()
        lin_count = connection.execute(
            text(
                "SELECT count(*) FROM import_row_lineage l "
                "JOIN raw_import_rows r ON r.id = l.raw_import_row_id "
                "WHERE r.batch_id = :b"
            ),
            {"b": batch_id},
        ).scalar_one()
    assert int(fp_count) == 1
    assert int(lin_count) >= 1


def test_revenue_commit_writes_lineage(
    client, admin, app, fake, tmp_path
) -> None:
    tenant_id, company_id = _ready_revenue(client, admin, app, fake, tmp_path)
    source = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Продажи",
            "type": "file",
            "namespace": "sales-csv",
            "format": "csv",
            "dataset": "revenue",
        },
    )
    assert source.status_code == 200, source.text
    content = (_REV_FIXTURES / "revenue_ok.csv").read_bytes()
    uploaded = client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": source.json()["id"]},
        files={"upload": ("rev.csv", content, "application/octet-stream")},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert uploaded.status_code == 200, uploaded.text
    batch_id = uploaded.json()["id"]
    assert _commit(client, batch_id).status_code == 200
    with admin.connect() as connection:
        kinds = connection.execute(
            text(
                "SELECT DISTINCT entity_kind FROM import_row_lineage l "
                "JOIN raw_import_rows r ON r.id = l.raw_import_row_id "
                "WHERE r.batch_id = :b"
            ),
            {"b": batch_id},
        ).fetchall()
    assert {row[0] for row in kinds} == {"revenue_entry"}


def test_plan_commit_writes_lineage(client, admin, app, fake, tmp_path) -> None:
    from tests.integration.test_plan_api import FIXTURES as PLAN_FIXTURES
    from tests.integration.test_plan_api import _ready as plan_ready
    from tests.integration.test_plan_api import _upload as plan_upload
    from tests.integration.test_plan_api import _wallet as plan_wallet

    _tenant, company_id = plan_ready(client, admin, app, fake, tmp_path, "plan-lin@example.com")
    plan_wallet(client, company_id, "0.00")
    source = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "План",
            "type": "file",
            "namespace": "plan-prov-033",
            "format": "csv",
            "dataset": "plan",
        },
    )
    assert source.status_code == 200, source.text
    content = (PLAN_FIXTURES / "planned_ok.csv").read_bytes()
    uploaded = plan_upload(client, company_id, source.json()["id"], content, "plan-lin")
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["counts"]["new"] >= 1
    batch_id = uploaded.json()["id"]
    committed = _commit(client, batch_id)
    assert committed.status_code == 200, committed.text
    assert committed.json().get("rows_committed", 0) >= 1
    with admin.connect() as connection:
        kind = connection.execute(
            text(
                "SELECT entity_kind FROM import_row_lineage l "
                "JOIN raw_import_rows r ON r.id = l.raw_import_row_id "
                "WHERE r.batch_id = :b LIMIT 1"
            ),
            {"b": batch_id},
        ).scalar_one()
    assert kind == "planned_event"


def _ready_revenue(client, admin, app, fake, tmp_path):
    from tests.integration.test_revenue_api import _ready as rev_ready

    return rev_ready(client, admin, app, fake, tmp_path, "prov-rev@example.com")
