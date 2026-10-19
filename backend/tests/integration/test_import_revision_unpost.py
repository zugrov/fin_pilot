from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from tests.integration.conftest import login, open_workspace, pay, register_and_verify

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"
CASH_HEADER = (
    "external_id,wallet_code,business_date,direction,amount,currency,"
    "counterparty_inn,counterparty_name,description,document_number,category_code,direction_code,"
    "source_entity_id,source_revision,operation"
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


def _source(client, company_id: str, wallet_id: str, **extra) -> dict:
    payload = {
        "name": extra.pop("name", "Банк"),
        "type": "file",
        "namespace": extra.pop("namespace", "bank"),
        "format": extra.pop("format", "csv"),
        "encoding": "utf-8",
        "authoritative": True,
        "wallet_id": wallet_id,
    }
    payload.update(extra)
    created = client.post(f"/api/v1/companies/{company_id}/sources", json=payload)
    assert created.status_code == 200, created.text
    return created.json()


def _upload(client, company_id: str, connection_id: str, body: str, key: str):
    return client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": connection_id},
        files={"upload": ("cash.csv", body.encode(), "text/csv")},
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


def test_stale_revision_rejected_on_commit(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "stale@example.com")
    source = _source(client, company_id, wallet_id)
    old_batch = _upload(
        client,
        company_id,
        source["id"],
        CASH_HEADER + "\n" + "pay-r,main,2026-10-10,in,100.00,RUB,,,Rev,,,,,1,upsert\n",
        "stale-old",
    )
    new_batch = _upload(
        client,
        company_id,
        source["id"],
        CASH_HEADER + "\n" + "pay-r,main,2026-10-10,in,200.00,RUB,,,Rev2,,,,,2,upsert\n",
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
    source = _source(client, company_id, wallet_id)
    create_body = (
        CASH_HEADER
        + "\n"
        + "u1,main,2026-10-10,in,50.00,RUB,,,Create,,,,,1,upsert\n"
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
