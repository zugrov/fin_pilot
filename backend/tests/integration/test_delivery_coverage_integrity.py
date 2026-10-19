"""FA-R02.4: coverage invalidation, versions, migration guard."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from tests.integration.test_delivery_control_totals import (
    _cash_totals_claim,
    _completeness,
    _envelope_v11,
    _one_part,
    _post_ingest,
    _rows,
)
from tests.integration.test_import_revision_unpost import (
    CASH_HEADER,
    DatasetCase,
    _cash_file,
    _cash_row,
    _ready,
    _source,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"
BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture
def session_ingest(app):
    app.state.settings.session_ingest_enabled = True
    yield
    app.state.settings.session_ingest_enabled = False


def _ingest_and_reconcile(
    client,
    company_id,
    source_id,
    blob,
    key: str,
    *,
    record_count: int,
    cash_in: str,
) -> tuple[str, str]:
    created = _post_ingest(
        client,
        company_id,
        _envelope_v11(
            source_id,
            key,
            _one_part(blob),
            control_totals=_cash_totals_claim(record_count, cash_in),
        ),
        [blob],
        key,
    )
    assert created.status_code == 201, created.text
    delivery_id = created.json()["delivery_id"]
    batch_id = created.json()["parts"][0]["batch_id"]
    commit = client.post(f"/api/v1/imports/{batch_id}/commit?delivery_id={delivery_id}")
    assert commit.status_code == 200, commit.text
    rec = client.post(
        f"/api/v1/ingestions/{delivery_id}/reconcile",
        json={"reconciliation_basis": "initial reconcile"},
        headers={"Idempotency-Key": f"rec-{key}"},
    )
    assert rec.status_code == 200, rec.text
    return delivery_id, rec.json()["id"]


def test_invalidation_after_second_import_blocks_fresh_reconcile(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "inv@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "inv", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob1 = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    delivery_id, coverage_id = _ingest_and_reconcile(
        client, company_id, source["id"], blob1, "k1", record_count=2, cash_in="3000.00"
    )
    state_before = _rows(
        admin,
        "SELECT state FROM dataset_coverage WHERE id = CAST(:id AS uuid)",
        {"id": coverage_id},
    )[0][0]
    assert state_before == "reconciled"
    blob2 = _cash_file(_cash_row("new-after", "500.00")).encode("utf-8")
    key2 = uuid4().hex
    second = _post_ingest(
        client,
        company_id,
        _envelope_v11(
            source["id"],
            key2,
            _one_part(blob2),
            control_totals=_cash_totals_claim(1, "500.00"),
        ),
        [blob2],
        key2,
    )
    batch2 = second.json()["parts"][0]["batch_id"]
    client.post(f"/api/v1/imports/{batch2}/commit?delivery_id={second.json()['delivery_id']}")
    state_after = _rows(
        admin,
        "SELECT state FROM dataset_coverage WHERE id = CAST(:id AS uuid)",
        {"id": coverage_id},
    )[0][0]
    assert state_after == "superseded"
    stale = client.post(
        f"/api/v1/ingestions/{delivery_id}/reconcile",
        json={"reconciliation_basis": "повтор после импорта"},
        headers={"Idempotency-Key": "fresh-key"},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "coverage_stale"
    active = _rows(
        admin,
        "SELECT count(*) FROM dataset_coverage WHERE connection_id = CAST(:c AS uuid) "
        "AND state = 'reconciled'",
        {"c": source["id"]},
    )[0][0]
    assert active == 0


def test_replay_commit_does_not_resurrect_superseded_coverage(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "replay@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "replay", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    created = _post_ingest(
        client,
        company_id,
        _envelope_v11(
            source["id"],
            key,
            _one_part(blob),
            control_totals=_cash_totals_claim(2, "3000.00"),
        ),
        [blob],
        key,
    )
    delivery_id = created.json()["delivery_id"]
    batch_id = created.json()["parts"][0]["batch_id"]
    client.post(f"/api/v1/imports/{batch_id}/commit?delivery_id={delivery_id}")
    rec = client.post(
        f"/api/v1/ingestions/{delivery_id}/reconcile",
        json={"reconciliation_basis": "once"},
        headers={"Idempotency-Key": "once"},
    )
    coverage_id = rec.json()["id"]
    again = client.post(f"/api/v1/imports/{batch_id}/commit?delivery_id={delivery_id}")
    assert again.status_code == 200
    state = _rows(
        admin,
        "SELECT state FROM dataset_coverage WHERE id = CAST(:id AS uuid)",
        {"id": coverage_id},
    )[0][0]
    assert state == "reconciled"


def test_migration_0014_sql_downgrade_guard(migrated_database) -> None:
    path = BACKEND / "alembic" / "sql" / "0014_delivery_validation_coverage_downgrade.sql"
    sql = path.read_text(encoding="utf-8")
    assert "downgrade_blocked" in sql
    assert "dataset_coverage" in sql


def test_different_periods_keep_independent_reconciled_versions(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "periods@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "per2", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = _cash_file(_cash_row("p-1", "100.00")).encode("utf-8")
    key_a = uuid4().hex
    env_a = _envelope_v11(
        source["id"],
        key_a,
        _one_part(blob),
        period_from="2026-10-01",
        period_to="2026-10-15",
        control_totals=_cash_totals_claim(1, "100.00"),
        completeness_claim=_completeness("2026-10-15"),
    )
    a = _post_ingest(client, company_id, env_a, [blob], key_a)
    d_a = a.json()["delivery_id"]
    b_a = a.json()["parts"][0]["batch_id"]
    client.post(f"/api/v1/imports/{b_a}/commit?delivery_id={d_a}")
    rec_a = client.post(
        f"/api/v1/ingestions/{d_a}/reconcile",
        json={"reconciliation_basis": "oct first half"},
        headers={"Idempotency-Key": "pa"},
    )
    assert rec_a.status_code == 200
    row_b = list(_cash_row("p-2", "100.00"))
    row_b[2] = "2026-10-20"
    blob_b = _cash_file(tuple(row_b)).encode("utf-8")
    key_b = uuid4().hex
    env_b = _envelope_v11(
        source["id"],
        key_b,
        _one_part(blob_b),
        period_from="2026-10-16",
        period_to="2026-10-31",
        control_totals=_cash_totals_claim(1, "100.00"),
        completeness_claim=_completeness("2026-10-31"),
    )
    b = _post_ingest(client, company_id, env_b, [blob_b], key_b)
    d_b = b.json()["delivery_id"]
    b_b = b.json()["parts"][0]["batch_id"]
    client.post(f"/api/v1/imports/{b_b}/commit?delivery_id={d_b}")
    rec_b = client.post(
        f"/api/v1/ingestions/{d_b}/reconcile",
        json={"reconciliation_basis": "oct second half"},
        headers={"Idempotency-Key": "pb"},
    )
    assert rec_b.status_code == 200
    active = _rows(
        admin,
        "SELECT count(*) FROM dataset_coverage WHERE connection_id = CAST(:c AS uuid) "
        "AND state = 'reconciled'",
        {"c": source["id"]},
    )[0][0]
    assert active == 1
    history = _rows(
        admin,
        "SELECT count(*) FROM dataset_coverage WHERE connection_id = CAST(:c AS uuid) "
        "AND state IN ('reconciled', 'superseded')",
        {"c": source["id"]},
    )[0][0]
    assert history >= 2
    period_b = _rows(
        admin,
        "SELECT period_start::text, period_end::text FROM dataset_coverage "
        "WHERE delivery_id = CAST(:d AS uuid) AND state = 'reconciled'",
        {"d": d_b},
    )[0]
    assert period_b == ("2026-10-16", "2026-10-31")
