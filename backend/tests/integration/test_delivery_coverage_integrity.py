"""FA-R02.4: coverage invalidation, versions, migration guard."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import BACKEND, HEAD_REVISION
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
PREV_0013 = "20261019_0013"


def _current_revision(engine) -> str | None:
    with engine.connect() as connection:
        return connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _alembic_downgrade(target: str) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    previous = os.getcwd()
    os.chdir(BACKEND)
    try:
        command.downgrade(config, target)
    finally:
        os.chdir(previous)


@pytest.fixture
def restore_head(migrated_database):
    yield
    if _current_revision(migrated_database) != HEAD_REVISION:
        config = Config(str(BACKEND / "alembic.ini"))
        previous = os.getcwd()
        os.chdir(BACKEND)
        try:
            command.upgrade(config, "head")
        finally:
            os.chdir(previous)


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


def test_concurrent_reconcile_same_scope_single_active_version(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "conc-rec@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "crec", "cash_transactions", True)
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
    commit_first = client.post(
        f"/api/v1/imports/{batch_id}/commit?delivery_id={delivery_id}"
    )
    assert commit_first.status_code == 200
    barrier = threading.Barrier(2)
    results: list[tuple[int, str | None]] = []
    errors: list[BaseException] = []

    def worker(idem: str) -> None:
        try:
            barrier.wait(timeout=30)
            resp = client.post(
                f"/api/v1/ingestions/{delivery_id}/reconcile",
                json={"reconciliation_basis": f"basis-{idem}"},
                headers={"Idempotency-Key": idem},
            )
            body_id = resp.json().get("id") if resp.headers.get("content-type", "").startswith(
                "application/json"
            ) else None
            results.append((resp.status_code, body_id))
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=("conc-a",)),
        threading.Thread(target=worker, args=("conc-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
        assert not thread.is_alive()
    if errors:
        raise errors[0]
    assert all(code == 200 for code, _ in results)
    active = _rows(
        admin,
        "SELECT count(*) FROM dataset_coverage WHERE connection_id = CAST(:c AS uuid) "
        "AND state = 'reconciled'",
        {"c": source["id"]},
    )[0][0]
    assert active == 1
    versions = _rows(
        admin,
        "SELECT version FROM dataset_coverage WHERE connection_id = CAST(:c AS uuid) "
        "AND state = 'reconciled'",
        {"c": source["id"]},
    )
    assert len(versions) == 1
    audit = _rows(
        admin,
        "SELECT count(*) FROM audit_log WHERE action = 'delivery_coverage_reconciled'",
    )[0][0]
    assert audit == 2


def _race_reconcile_vs_import(
    client,
    admin,
    app,
    fake,
    tmp_path,
    *,
    reconcile_first: bool,
) -> None:
    company_id, wallet_id = _ready(
        client,
        admin,
        app,
        fake,
        tmp_path,
        f"race-{'r' if reconcile_first else 'i'}@example.com",
    )
    case = DatasetCase("cash", "cash", CASH_HEADER, "race", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob1 = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key1 = uuid4().hex
    first = _post_ingest(
        client,
        company_id,
        _envelope_v11(
            source["id"],
            key1,
            _one_part(blob1),
            control_totals=_cash_totals_claim(2, "3000.00"),
        ),
        [blob1],
        key1,
    )
    delivery1 = first.json()["delivery_id"]
    batch1 = first.json()["parts"][0]["batch_id"]
    client.post(f"/api/v1/imports/{batch1}/commit?delivery_id={delivery1}")
    rec = client.post(
        f"/api/v1/ingestions/{delivery1}/reconcile",
        json={"reconciliation_basis": "initial"},
        headers={"Idempotency-Key": f"init-{key1}"},
    )
    assert rec.status_code == 200
    coverage1 = rec.json()["id"]
    blob2 = _cash_file(_cash_row("race-new", "10.00")).encode("utf-8")
    key2 = uuid4().hex
    second = _post_ingest(
        client,
        company_id,
        _envelope_v11(
            source["id"],
            key2,
            _one_part(blob2),
            control_totals=_cash_totals_claim(1, "10.00"),
        ),
        [blob2],
        key2,
    )
    delivery2 = second.json()["delivery_id"]
    batch2 = second.json()["parts"][0]["batch_id"]
    start = threading.Barrier(2)
    turn_done = threading.Event()
    outcomes: list[int] = []
    errors: list[BaseException] = []

    def do_reconcile() -> None:
        try:
            start.wait(timeout=30)
            if reconcile_first:
                resp = client.post(
                    f"/api/v1/ingestions/{delivery1}/reconcile",
                    json={"reconciliation_basis": "race retry"},
                    headers={"Idempotency-Key": f"race-rec-{key2}"},
                )
                outcomes.append(resp.status_code)
                turn_done.set()
            else:
                assert turn_done.wait(timeout=30)
                resp = client.post(
                    f"/api/v1/ingestions/{delivery1}/reconcile",
                    json={"reconciliation_basis": "race retry"},
                    headers={"Idempotency-Key": f"race-rec-{key2}"},
                )
                outcomes.append(resp.status_code)
        except BaseException as exc:
            errors.append(exc)

    def do_commit() -> None:
        try:
            start.wait(timeout=30)
            if reconcile_first:
                assert turn_done.wait(timeout=30)
                resp = client.post(f"/api/v1/imports/{batch2}/commit?delivery_id={delivery2}")
                outcomes.append(resp.status_code)
            else:
                resp = client.post(f"/api/v1/imports/{batch2}/commit?delivery_id={delivery2}")
                outcomes.append(resp.status_code)
                turn_done.set()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=do_reconcile),
        threading.Thread(target=do_commit),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
        assert not thread.is_alive()
    if errors:
        raise errors[0]
    assert 200 in outcomes
    state1 = _rows(
        admin,
        "SELECT state FROM dataset_coverage WHERE id = CAST(:id AS uuid)",
        {"id": coverage1},
    )[0][0]
    assert state1 == "superseded"
    active = _rows(
        admin,
        "SELECT count(*) FROM dataset_coverage WHERE connection_id = CAST(:c AS uuid) "
        "AND state = 'reconciled' AND delivery_id = CAST(:d AS uuid)",
        {"c": source["id"], "d": delivery1},
    )[0][0]
    assert active == 0


def test_concurrent_reconcile_then_import_invalidates_stale_delivery(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    _race_reconcile_vs_import(
        client, admin, app, fake, tmp_path, reconcile_first=True
    )


def test_concurrent_import_then_reconcile_rejects_or_supersedes(
    client, admin, app, fake, tmp_path, session_ingest
) -> None:
    _race_reconcile_vs_import(
        client, admin, app, fake, tmp_path, reconcile_first=False
    )


def test_runtime_downgrade_0014_blocked_with_dataset_coverage(
    client, admin, app, fake, tmp_path, migrated_database, restore_head, session_ingest
) -> None:
    assert_finpilot_test_database(migrated_database)
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "dn-a@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "dna", "cash_transactions", True)
    source = _source(client, company_id, wallet_id, case)
    blob = FIXTURES.joinpath("cash_ok.csv").read_bytes()
    key = uuid4().hex
    _ingest_and_reconcile(
        client, company_id, source["id"], blob, key, record_count=2, cash_in="3000.00"
    )
    cov_count = _rows(admin, "SELECT count(*) FROM dataset_coverage")[0][0]
    assert cov_count >= 1
    with migrated_database.connect() as connection:
        revision_before = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert revision_before == HEAD_REVISION
    with pytest.raises(Exception) as exc:
        _alembic_downgrade(PREV_0013)
    assert "downgrade_blocked" in str(exc.value)
    with migrated_database.connect() as connection:
        revision_after = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        table_exists = connection.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'dataset_coverage'"
            )
        ).fetchone()
        col_exists = connection.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'ingestion_deliveries' AND column_name = 'validation_status'"
            )
        ).fetchone()
    assert revision_after == HEAD_REVISION
    assert table_exists is not None
    assert col_exists is not None
    assert _rows(admin, "SELECT count(*) FROM dataset_coverage")[0][0] >= 1


def test_runtime_downgrade_0014_blocked_with_delivery_metadata_only(
    client, admin, app, fake, tmp_path, migrated_database, restore_head, session_ingest
) -> None:
    assert_finpilot_test_database(migrated_database)
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "dn-b@example.com")
    case = DatasetCase("cash", "cash", CASH_HEADER, "dnb", "cash_transactions", True)
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
    assert created.json()["validation_status"] == "matched"
    with admin.connect() as connection:
        connection.execute(text("DELETE FROM dataset_coverage"))
        connection.commit()
    assert _rows(admin, "SELECT count(*) FROM dataset_coverage")[0][0] == 0
    meta = _rows(
        admin,
        "SELECT count(*) FROM ingestion_deliveries WHERE validation_status <> 'not_checked'",
    )[0][0]
    assert meta >= 1
    with pytest.raises(Exception) as exc:
        _alembic_downgrade(PREV_0013)
    assert "downgrade_blocked" in str(exc.value)
    assert _current_revision(migrated_database) == HEAD_REVISION
    with migrated_database.connect() as connection:
        connection.execute(text("SELECT 1"))


def _revenue_source(client, company_id: str) -> str:
    created = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Продажи",
            "type": "file",
            "namespace": "sales-cov",
            "format": "csv",
            "dataset": "revenue",
        },
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _coverage_through_independent(admin, source_id: str) -> str | None:
    with admin.connect() as connection:
        return connection.execute(
            text(
                "SELECT coverage_through::text FROM source_connections "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": source_id},
        ).scalar_one_or_none()


def test_legacy_revenue_coverage_post_persists_through_scope_lock(
    client, admin, app, fake, tmp_path
) -> None:
    company_id, _wallet_id = _ready(
        client, admin, app, fake, tmp_path, "legacy-scope-lock@example.com"
    )
    source_id = _revenue_source(client, company_id)
    company_tz = _rows(
        admin,
        "SELECT timezone FROM companies WHERE id = CAST(:id AS uuid)",
        {"id": company_id},
    )[0][0]
    revenue_before = _rows(admin, "SELECT count(*) FROM revenue_entries")[0][0]
    cash_before = _rows(admin, "SELECT count(*) FROM cash_transactions")[0][0]

    first_date = "2026-10-15"
    first = client.post(
        f"/api/v1/companies/{company_id}/sources/{source_id}/coverage",
        json={"coverage_through": first_date},
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["coverage_through"] == first_date
    assert body["dataset"] == "revenue"
    assert _coverage_through_independent(admin, source_id) == first_date

    claimed = _rows(
        admin,
        "SELECT state, version, connection_id::text, company_id::text, period_timezone, dataset "
        "FROM dataset_coverage WHERE connection_id = CAST(:c AS uuid) ORDER BY version",
        {"c": source_id},
    )
    assert len(claimed) == 1
    assert claimed[0][0] == "claimed"
    assert claimed[0][1] == 1
    assert claimed[0][2] == source_id
    assert claimed[0][3] == company_id
    assert claimed[0][4] == company_tz
    assert claimed[0][5] == "revenue"
    reconciled = _rows(
        admin,
        "SELECT count(*) FROM dataset_coverage WHERE connection_id = CAST(:c AS uuid) "
        "AND state = 'reconciled'",
        {"c": source_id},
    )[0][0]
    assert reconciled == 0
    audit_first = _rows(
        admin,
        "SELECT count(*) FROM audit_log WHERE action = 'revenue_coverage_set' "
        "AND entity_id = CAST(:id AS uuid)",
        {"id": source_id},
    )[0][0]
    assert audit_first == 1
    assert _rows(admin, "SELECT count(*) FROM revenue_entries")[0][0] == revenue_before
    assert _rows(admin, "SELECT count(*) FROM cash_transactions")[0][0] == cash_before

    second_date = "2026-10-31"
    second = client.post(
        f"/api/v1/companies/{company_id}/sources/{source_id}/coverage",
        json={"coverage_through": second_date},
    )
    assert second.status_code == 200, second.text
    assert second.json()["coverage_through"] == second_date
    assert _coverage_through_independent(admin, source_id) == second_date

    periods = _rows(
        admin,
        "SELECT version, state, period_start::text, period_end::text "
        "FROM dataset_coverage WHERE connection_id = CAST(:c AS uuid) ORDER BY created_at",
        {"c": source_id},
    )
    assert len(periods) == 2
    assert periods[0] == (1, "claimed", first_date, first_date)
    assert periods[1] == (1, "claimed", second_date, second_date)

    third = client.post(
        f"/api/v1/companies/{company_id}/sources/{source_id}/coverage",
        json={"coverage_through": second_date},
    )
    assert third.status_code == 200, third.text
    scope_versions = _rows(
        admin,
        "SELECT version FROM dataset_coverage WHERE connection_id = CAST(:c AS uuid) "
        "AND period_start = CAST(:d AS date) AND period_end = CAST(:d AS date) "
        "ORDER BY version",
        {"c": source_id, "d": second_date},
    )
    assert scope_versions == [(1,), (2,)]
    audit_total = _rows(
        admin,
        "SELECT count(*) FROM audit_log WHERE action = 'revenue_coverage_set' "
        "AND entity_id = CAST(:id AS uuid)",
        {"id": source_id},
    )[0][0]
    assert audit_total == 3
    assert _rows(admin, "SELECT count(*) FROM revenue_entries")[0][0] == revenue_before
    assert _rows(admin, "SELECT count(*) FROM cash_transactions")[0][0] == cash_before
