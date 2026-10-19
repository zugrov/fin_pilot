import os
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from app.clock import now
from app.errors import AppError
from app.models.identity import User
from app.security.access import require_membership
from app.services import import_service
from sqlalchemy import text
from tests.integration.conftest import (
    BACKEND,
    HEAD_REVISION,
    login,
    open_workspace,
    pay,
    register_and_verify,
)

META = ",source_entity_id,source_revision,operation"
CASH_HEADER = (
    "external_id,wallet_code,business_date,direction,amount,currency,"
    "counterparty_inn,counterparty_name,description,document_number,category_code,direction_code"
    + META
)
REVENUE_HEADER = (
    "external_id,recognition_date,document_number,counterparty_inn,amount_ex_vat,vat_amount,"
    "amount_inc_vat,entry_type,direction_code" + META
)
PLAN_HEADER = (
    "external_id,direction,amount,currency,due_date,expected_date,category_code,"
    "counterparty_inn,confidence,priority,wallet_code" + META
)
BUDGET_HEADER = (
    "year,month,basis,metric_type,category_code,direction_code,amount,distribution_method" + META
)
PREV_REVISION = "20261019_0012"


@dataclass(frozen=True)
class DatasetCase:
    name: str
    dataset: str
    header: str
    namespace: str
    financial_table: str
    needs_wallet: bool


DATASET_CASES = (
    DatasetCase("cash", "cash", CASH_HEADER, "bank-rev", "cash_transactions", True),
    DatasetCase("revenue", "revenue", REVENUE_HEADER, "sales-rev", "revenue_entries", False),
    DatasetCase("plan", "plan", PLAN_HEADER, "plan-rev", "planned_cash_events", False),
    DatasetCase("budget", "budget", BUDGET_HEADER, "budget-rev", "budget_lines", False),
)


def _ready(client, admin, app, fake, tmp_path, email: str) -> tuple[str, str]:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Rev")
    company = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Фирма", "kind": "company"},
    )
    assert company.status_code == 200, company.text
    company_id = company.json()["id"]
    pay(client, app, fake, 1, "month")
    client.post(f"/api/v1/billing/companies/{company_id}/activate")
    wallet = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Расчётный", "type": "bank", "code": "main"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert wallet.status_code == 200, wallet.text
    return company_id, wallet.json()["id"]


def _source(client, company_id: str, wallet_id: str | None, case: DatasetCase, **extra) -> dict:
    payload = {
        "name": extra.pop("name", case.name),
        "type": "file",
        "namespace": extra.pop("namespace", case.namespace),
        "format": extra.pop("format", "csv"),
        "encoding": "utf-8",
        "authoritative": True,
        "dataset": case.dataset,
    }
    if case.needs_wallet:
        payload["wallet_id"] = wallet_id
    payload.update(extra)
    created = client.post(f"/api/v1/companies/{company_id}/sources", json=payload)
    assert created.status_code == 200, created.text
    return created.json()


def _upload(client, company_id: str, connection_id: str, body: str, key: str):
    return client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": connection_id},
        files={"upload": ("import.csv", body.encode(), "text/csv")},
        headers={"Idempotency-Key": key},
    )


def _commit(client, batch_id: str):
    return client.post(f"/api/v1/imports/{batch_id}/commit")


def _watermark(admin, external_id: str) -> int | None:
    with admin.connect() as connection:
        value = connection.execute(
            text("SELECT last_source_revision FROM source_identities WHERE external_id = :id"),
            {"id": external_id},
        ).scalar_one_or_none()
    return None if value is None else int(value)


def _tx_count(admin) -> int:
    with admin.connect() as connection:
        return int(connection.execute(text("SELECT count(*) FROM cash_transactions")).scalar_one())


def _financial_count(admin, table: str) -> int:
    with admin.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def _batch_status(admin, batch_id: str) -> str:
    with admin.connect() as connection:
        return str(
            connection.execute(
                text("SELECT status FROM import_batches WHERE id = :id"),
                {"id": batch_id},
            ).scalar_one()
        )


def _user_id(admin, email: str) -> UUID:
    with admin.connect() as connection:
        value = connection.execute(
            text("SELECT id FROM users WHERE normalized_email = :email"),
            {"email": email.strip().lower()},
        ).scalar_one()
    return UUID(str(value))


def _tenant_id(client) -> UUID:
    return UUID(client.headers["X-Tenant-Id"])


def _cash_line(external_id: str, amount: str, revision: int) -> str:
    return (
        f"{external_id},main,2026-10-10,in,{amount},RUB,,,Rev,,,,,{revision},upsert\n"
    )


def _revenue_line(external_id: str, amount_ex: str, revision: int) -> str:
    ex = float(amount_ex)
    vat = round(ex * 0.2, 2)
    inc = round(ex + vat, 2)
    return (
        f"{external_id},2026-10-10,15,7700000001,{amount_ex},{vat:.2f},{inc:.2f},sale,,"
        f",{revision},upsert\n"
    )


def _plan_line(external_id: str, amount: str, revision: int) -> str:
    return (
        f"{external_id},out,{amount},RUB,2026-10-20,2026-10-20,operating,,expected,normal,main,"
        f",{revision},upsert\n"
    )


def _budget_line(revision: int, amount: str = "100000.00") -> str:
    return (
        f"2026,10,cash,cash_out,operating,,{amount},calendar_days,bud-rev-1,{revision},upsert\n"
    )


def _line_for(case: DatasetCase, external_id: str, amount: str, revision: int) -> str:
    if case.dataset == "cash":
        return _cash_line(external_id, amount, revision)
    if case.dataset == "revenue":
        return _revenue_line(external_id, amount, revision)
    if case.dataset == "plan":
        return _plan_line(external_id, amount, revision)
    return _budget_line(revision, amount)


def _parallel_commit(
    app, tenant_id: UUID, user_id: UUID, batch_ids: list[str]
) -> list[tuple[int, int, dict]]:
    barrier = threading.Barrier(len(batch_ids))
    results: list[tuple[int, int, dict]] = []
    lock = threading.Lock()

    def worker(slot: int, batch_id: str) -> None:
        session = app.state.session_factory()
        try:
            user = session.get(User, user_id)
            assert user is not None
            membership = require_membership(session, user.id, tenant_id)
            barrier.wait()
            try:
                payload = import_service.commit_import(
                    session,
                    membership,
                    user,
                    app.state.settings,
                    UUID(batch_id),
                    now(),
                )
                session.commit()
                body = {"status": payload.get("status"), "code": None}
            except AppError as exc:
                session.rollback()
                body = {"status": None, "code": exc.code}
                with lock:
                    results.append((slot, exc.status_code, body))
                return
            with lock:
                results.append((slot, 200, body))
        finally:
            session.close()

    threads = [
        threading.Thread(target=worker, args=(index, batch_id))
        for index, batch_id in enumerate(batch_ids)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
        assert not thread.is_alive(), "commit thread did not finish"
    return sorted(results, key=lambda item: item[0])


def _alembic_downgrade(target: str) -> None:
    config = Config(str(BACKEND / "alembic.ini"))
    previous = os.getcwd()
    os.chdir(BACKEND)
    try:
        command.downgrade(config, target)
    finally:
        os.chdir(previous)


def test_stale_revision_rejected_on_commit(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "stale@example.com")
    source = _source(client, company_id, wallet_id, DATASET_CASES[0])
    old_batch = _upload(
        client,
        company_id,
        source["id"],
        CASH_HEADER + "\n" + _cash_line("pay-r", "100.00", 1),
        "stale-old",
    )
    new_batch = _upload(
        client,
        company_id,
        source["id"],
        CASH_HEADER + "\n" + _cash_line("pay-r", "200.00", 2),
        "stale-new",
    )
    assert old_batch.status_code == 200, old_batch.text
    assert new_batch.status_code == 200, new_batch.text
    assert _commit(client, new_batch.json()["id"]).status_code == 200
    assert _watermark(admin, "pay-r") == 2
    stale_commit = _commit(client, old_batch.json()["id"])
    assert stale_commit.status_code == 409
    assert stale_commit.json()["code"] == "stale_revision"
    assert _tx_count(admin) == 1
    assert _watermark(admin, "pay-r") == 2


def test_unpost_review_without_financial_change(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "unpost@example.com")
    source = _source(client, company_id, wallet_id, DATASET_CASES[0])
    create_body = (
        CASH_HEADER
        + "\n"
        + _cash_line("u1", "50.00", 1)
        + "u1,,,,,,,,,,,,,2,unpost\n"
    )
    uploaded = _upload(client, company_id, source["id"], create_body, "unpost-a")
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["counts"]["unpost"] == 1
    assert any(row.get("review_reason") == "unpost" for row in body["rows"])
    committed = _commit(client, body["id"])
    assert committed.status_code == 200, committed.text
    payload = committed.json()
    assert payload["status"] == "completed_with_errors"
    assert "rows_in_review" in payload["quality_flags"]
    assert _tx_count(admin) == 1
    assert _watermark(admin, "u1") == 1


def test_migration_sql_downgrade_guard_0013() -> None:
    sql = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "sql"
        / "0013_source_revision_unpost_downgrade.sql"
    ).read_text(encoding="utf-8")
    assert "downgrade_blocked" in sql
    assert "last_source_revision" in sql
    assert "operation" in sql


def test_concurrent_first_identity_single_financial_row(
    client, admin, app, fake, tmp_path
) -> None:
    email = "conc-first@example.com"
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, email)
    case = DATASET_CASES[0]
    source = _source(client, company_id, wallet_id, case)
    external_id = "conc-first"
    batch_a = _upload(
        client,
        company_id,
        source["id"],
        case.header + "\n" + _line_for(case, external_id, "100.00", 1),
        "conc-a",
    )
    batch_b = _upload(
        client,
        company_id,
        source["id"],
        case.header + "\n" + _line_for(case, external_id, "200.00", 2),
        "conc-b",
    )
    assert batch_a.status_code == batch_b.status_code == 200
    results = _parallel_commit(
        app,
        _tenant_id(client),
        _user_id(admin, email),
        [batch_a.json()["id"], batch_b.json()["id"]],
    )
    assert len(results) == 2
    assert all(status == 200 for _, status, _ in results)
    assert _financial_count(admin, case.financial_table) == 1
    assert _watermark(admin, external_id) == 2


def test_concurrent_existing_identity_keeps_max_revision(
    client, admin, app, fake, tmp_path
) -> None:
    email = "conc-exist@example.com"
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, email)
    case = DATASET_CASES[0]
    source = _source(client, company_id, wallet_id, case)
    external_id = "conc-exist"
    seed = _upload(
        client,
        company_id,
        source["id"],
        case.header + "\n" + _line_for(case, external_id, "100.00", 1),
        "conc-seed",
    )
    assert _commit(client, seed.json()["id"]).status_code == 200
    batch_mid = _upload(
        client,
        company_id,
        source["id"],
        case.header + "\n" + _line_for(case, external_id, "250.00", 2),
        "conc-mid",
    )
    batch_high = _upload(
        client,
        company_id,
        source["id"],
        case.header + "\n" + _line_for(case, external_id, "300.00", 3),
        "conc-high",
    )
    results = _parallel_commit(
        app,
        _tenant_id(client),
        _user_id(admin, email),
        [batch_mid.json()["id"], batch_high.json()["id"]],
    )
    codes = {body["code"] for _, _, body in results}
    statuses = {status for _, status, _ in results}
    assert statuses == {200}
    assert _watermark(admin, external_id) == 3
    assert _financial_count(admin, case.financial_table) == 1
    if 409 in statuses:
        assert "stale_revision" in codes


def test_sequential_revision_1_then_2_both_success(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "seq-12@example.com")
    case = DATASET_CASES[0]
    source = _source(client, company_id, wallet_id, case)
    external_id = "seq-12"
    first = _upload(
        client,
        company_id,
        source["id"],
        case.header + "\n" + _line_for(case, external_id, "100.00", 1),
        "seq-1",
    )
    second = _upload(
        client,
        company_id,
        source["id"],
        case.header + "\n" + _line_for(case, external_id, "200.00", 2),
        "seq-2",
    )
    assert _commit(client, first.json()["id"]).status_code == 200
    assert _commit(client, second.json()["id"]).status_code == 200
    assert _watermark(admin, external_id) == 2
    assert _financial_count(admin, case.financial_table) == 1


def test_sequential_revision_2_then_1_rejects_stale(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "seq-21@example.com")
    case = DATASET_CASES[0]
    source = _source(client, company_id, wallet_id, case)
    external_id = "seq-21"
    high = _upload(
        client,
        company_id,
        source["id"],
        case.header + "\n" + _line_for(case, external_id, "200.00", 2),
        "seq-high",
    )
    low = _upload(
        client,
        company_id,
        source["id"],
        case.header + "\n" + _line_for(case, external_id, "100.00", 1),
        "seq-low",
    )
    assert _commit(client, high.json()["id"]).status_code == 200
    stale = _commit(client, low.json()["id"])
    assert stale.status_code == 409
    assert stale.json()["code"] == "stale_revision"
    assert _watermark(admin, external_id) == 2


def test_late_row_conflict_rolls_back_batch(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "late-row@example.com")
    case = DATASET_CASES[0]
    source = _source(client, company_id, wallet_id, case)
    external_id = "late-row"
    seed = _upload(
        client,
        company_id,
        source["id"],
        case.header + "\n" + _line_for(case, external_id, "200.00", 2),
        "late-seed",
    )
    assert _commit(client, seed.json()["id"]).status_code == 200
    batch_id = _upload(
        client,
        company_id,
        source["id"],
        case.header
        + "\n"
        + _line_for(case, external_id, "300.00", 3)
        + _line_for(case, external_id, "400.00", 3),
        "late-batch",
    ).json()["id"]
    before_tx = _financial_count(admin, case.financial_table)
    before_wm = _watermark(admin, external_id)
    failed = _commit(client, batch_id)
    assert failed.status_code == 409
    assert failed.json()["code"] == "revision_payload_conflict"
    assert _financial_count(admin, case.financial_table) == before_tx
    assert _watermark(admin, external_id) == before_wm
    assert _batch_status(admin, batch_id) == "preview_ready"
    with admin.connect() as connection:
        audit = connection.execute(
            text(
                "SELECT count(*) FROM audit_log WHERE action = 'import_committed' "
                "AND entity_id = :id"
            ),
            {"id": batch_id},
        ).scalar_one()
    assert audit == 0


def test_identity_type_conflict(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "type-conf@example.com")
    cash_case = DATASET_CASES[0]
    cash_source = _source(client, company_id, wallet_id, cash_case)
    revenue_source = _source(
        client,
        company_id,
        wallet_id,
        DATASET_CASES[1],
        namespace="sales-type-conf",
    )
    external_id = "shared-ext"
    rev_body = REVENUE_HEADER + "\n" + _revenue_line(external_id, "100000.00", 1)
    rev_batch = _upload(client, company_id, revenue_source["id"], rev_body, "type-rev")
    assert _commit(client, rev_batch.json()["id"]).status_code == 200
    with admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE source_identities SET namespace = :cash_ns, connection_id = :conn "
                "WHERE external_id = :ext AND namespace = :rev_ns"
            ),
            {
                "cash_ns": cash_case.namespace,
                "conn": cash_source["id"],
                "ext": external_id,
                "rev_ns": "sales-type-conf",
            },
        )
    cash_batch = _upload(
        client,
        company_id,
        cash_source["id"],
        CASH_HEADER + "\n" + _cash_line(external_id, "100.00", 1),
        "type-cash",
    )
    assert cash_batch.status_code == 200, cash_batch.text
    preview = cash_batch.json()
    assert preview["counts"]["invalid"] == 1
    assert "identity_type_conflict" in preview["rows"][0]["errors"]
    committed = _commit(client, preview["id"])
    assert committed.status_code == 200, committed.text
    assert committed.json()["rows_committed"] == 0
    assert "partial_import" in committed.json()["quality_flags"]
    assert _tx_count(admin) == 0
    assert _financial_count(admin, "revenue_entries") == 1
    with admin.connect() as connection:
        identities = connection.execute(
            text("SELECT count(*) FROM source_identities WHERE external_id = :id"),
            {"id": external_id},
        ).scalar_one()
    assert identities == 1


def test_runtime_downgrade_0013_blocked_with_revision_data(
    client, admin, app, fake, tmp_path, migrated_database
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "downgrade@example.com")
    source = _source(client, company_id, wallet_id, DATASET_CASES[0])
    external_id = "downgrade-row"
    uploaded = _upload(
        client,
        company_id,
        source["id"],
        CASH_HEADER + "\n" + _cash_line(external_id, "100.00", 1),
        "downgrade-seed",
    )
    assert _commit(client, uploaded.json()["id"]).status_code == 200
    watermark_before = _watermark(admin, external_id)
    assert watermark_before == 1
    with migrated_database.connect() as connection:
        revision_before = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        operation_before = connection.execute(
            text("SELECT operation FROM raw_import_rows WHERE external_id = :id LIMIT 1"),
            {"id": external_id},
        ).scalar_one()
    assert revision_before == HEAD_REVISION
    with pytest.raises(Exception) as exc:
        _alembic_downgrade(PREV_REVISION)
    assert "downgrade_blocked" in str(exc.value)
    with migrated_database.connect() as connection:
        revision_after = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        column = connection.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'raw_import_rows' AND column_name = 'source_revision'"
            )
        ).fetchone()
        watermark_after = connection.execute(
            text("SELECT last_source_revision FROM source_identities WHERE external_id = :id"),
            {"id": external_id},
        ).scalar_one()
        operation_after = connection.execute(
            text("SELECT operation FROM raw_import_rows WHERE external_id = :id LIMIT 1"),
            {"id": external_id},
        ).scalar_one()
    assert revision_after == HEAD_REVISION
    assert column is not None
    assert watermark_after == watermark_before
    assert operation_after == operation_before


def test_higher_revision_same_payload_advances_watermark_only(
    client, admin, app, fake, tmp_path
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "wm-only@example.com")
    case = DATASET_CASES[0]
    source = _source(client, company_id, wallet_id, case)
    external_id = "wm-only"
    first = _upload(
        client,
        company_id,
        source["id"],
        case.header + "\n" + _line_for(case, external_id, "100.00", 1),
        "wm-1",
    )
    assert _commit(client, first.json()["id"]).status_code == 200
    repeat = _upload(
        client,
        company_id,
        source["id"],
        case.header + "\n" + _line_for(case, external_id, "100.00", 2),
        "wm-2",
    )
    assert _commit(client, repeat.json()["id"]).status_code == 200
    assert _watermark(admin, external_id) == 2
    assert _financial_count(admin, case.financial_table) == 1


def test_legacy_to_versioned_keeps_first_financial_revision(
    client, admin, app, fake, tmp_path
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "legacy@example.com")
    legacy_header = CASH_HEADER.replace(META, "")
    source = _source(client, company_id, wallet_id, DATASET_CASES[0])
    external_id = "legacy-v"
    legacy_line = f"{external_id},main,2026-10-10,in,100.00,RUB,,,Legacy,,,,\n"
    first = _upload(client, company_id, source["id"], legacy_header + "\n" + legacy_line, "leg-1")
    assert _commit(client, first.json()["id"]).status_code == 200
    versioned = _upload(
        client,
        company_id,
        source["id"],
        CASH_HEADER + "\n" + _cash_line(external_id, "100.00", 1),
        "leg-2",
    )
    assert _commit(client, versioned.json()["id"]).status_code == 200
    assert _financial_count(admin, "cash_transactions") == 1
    assert _watermark(admin, external_id) == 1


def test_missing_revision_after_versioned_does_not_change_financial_payload(
    client, admin, app, fake, tmp_path
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "miss-rev@example.com")
    source = _source(client, company_id, wallet_id, DATASET_CASES[0])
    external_id = "miss-rev"
    first = _upload(
        client,
        company_id,
        source["id"],
        CASH_HEADER + "\n" + _cash_line(external_id, "100.00", 1),
        "miss-v1",
    )
    second = _upload(
        client,
        company_id,
        source["id"],
        CASH_HEADER + "\n" + _cash_line(external_id, "100.00", 1),
        "miss-v2",
    )
    assert first.status_code == second.status_code == 200
    assert _commit(client, first.json()["id"]).status_code == 200
    repeated = _commit(client, second.json()["id"])
    assert repeated.status_code == 200
    assert _financial_count(admin, "cash_transactions") == 1
    assert _watermark(admin, external_id) == 1


def test_equal_revision_different_payload_conflicts(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "eq-rev@example.com")
    source = _source(client, company_id, wallet_id, DATASET_CASES[0])
    external_id = "eq-rev"
    first = _upload(
        client,
        company_id,
        source["id"],
        CASH_HEADER + "\n" + _cash_line(external_id, "100.00", 1),
        "eq-a",
    )
    conflict = _upload(
        client,
        company_id,
        source["id"],
        CASH_HEADER + "\n" + _cash_line(external_id, "200.00", 1),
        "eq-b",
    )
    assert first.status_code == conflict.status_code == 200
    assert _commit(client, first.json()["id"]).status_code == 200
    failed = _commit(client, conflict.json()["id"])
    assert failed.status_code == 409
    assert failed.json()["code"] == "revision_payload_conflict"
    assert _tx_count(admin) == 1
    assert _watermark(admin, external_id) == 1


@pytest.mark.parametrize("case", DATASET_CASES, ids=[item.name for item in DATASET_CASES])
def test_versioned_create_and_revise_watermark_per_dataset(
    client, admin, app, fake, tmp_path, case: DatasetCase
) -> None:
    email = f"ds-{case.name}@example.com"
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, email)
    source = _source(client, company_id, wallet_id, case)
    external_id = f"ds-{case.name}"
    create_body = case.header + "\n" + _line_for(case, external_id, "100000.00", 1)
    created = _upload(client, company_id, source["id"], create_body, f"ds-create-{case.name}")
    assert created.status_code == 200, created.text
    assert _commit(client, created.json()["id"]).status_code == 200
    assert _watermark(admin, external_id if case.dataset != "budget" else "bud-rev-1") == 1
    assert _financial_count(admin, case.financial_table) == 1
    revise_body = case.header + "\n" + _line_for(case, external_id, "110000.00", 2)
    revised = _upload(client, company_id, source["id"], revise_body, f"ds-revise-{case.name}")
    assert _commit(client, revised.json()["id"]).status_code == 200
    wm_key = external_id if case.dataset != "budget" else "bud-rev-1"
    assert _watermark(admin, wm_key) == 2
    assert _financial_count(admin, case.financial_table) == 1
