import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import psycopg
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.integration.conftest import (
    freeze,
    latest_link,
    login,
    open_workspace,
    pay,
    register_and_verify,
    token_from_link,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"
HEADER = (
    "external_id,wallet_code,business_date,direction,amount,currency,"
    "counterparty_inn,counterparty_name,description,document_number,category_code,direction_code\n"
)


def _ready(client, admin, app, fake, tmp_path, email: str) -> tuple[str, str]:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Импорт")
    company = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Фирма", "kind": "company"},
    )
    assert company.status_code == 200, company.text
    company_id = company.json()["id"]
    pay(client, app, fake, 1, "month")
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
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
        "type": extra.pop("type", "file"),
        "namespace": extra.pop("namespace", "bank"),
        "format": extra.pop("format", "csv"),
        "encoding": "utf-8",
        "authoritative": extra.pop("authoritative", True),
        "wallet_id": wallet_id,
    }
    payload.update(extra)
    created = client.post(f"/api/v1/companies/{company_id}/sources", json=payload)
    assert created.status_code == 200, created.text
    return created.json()


def _upload(client, company_id: str, connection_id: str, content: bytes, name: str, key: str):
    return client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": connection_id},
        files={"upload": (name, content, "application/octet-stream")},
        headers={"Idempotency-Key": key},
    )


def _commit(client, batch_id: str):
    return client.post(f"/api/v1/imports/{batch_id}/commit")


def _tx_count(admin) -> int:
    with admin.connect() as connection:
        return int(connection.execute(text("SELECT count(*) FROM cash_transactions")).scalar_one())


def test_i1_repeat_file_creates_nothing_new(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "i1@example.com")
    source = _source(client, company_id, wallet_id)
    content = (FIXTURES / "cash_ok.csv").read_bytes()
    first = _upload(client, company_id, source["id"], content, "cash.csv", "i1-a")
    assert first.status_code == 200, first.text
    assert _commit(client, first.json()["id"]).status_code == 200
    assert _tx_count(admin) == 2
    second = _upload(client, company_id, source["id"], content, "cash.csv", "i1-b")
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert _commit(client, second.json()["id"]).status_code == 200
    assert _tx_count(admin) == 2


def test_i2_same_fingerprint_different_ids_stay_separate(
    client, admin, app, fake, tmp_path
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "i2@example.com")
    source = _source(client, company_id, wallet_id, namespace="bank-2")
    uploaded = _upload(
        client,
        company_id,
        source["id"],
        (FIXTURES / "cash_ok.csv").read_bytes(),
        "cash.csv",
        "i2",
    )
    assert uploaded.json()["counts"]["new"] == 2
    committed = _commit(client, uploaded.json()["id"])
    assert committed.status_code == 200, committed.text
    assert _tx_count(admin) == 2


def test_i3_bank_and_clientbank_share_one_transaction(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "i3@example.com")
    bank = _source(client, company_id, wallet_id, namespace="bank")
    body = (
        HEADER + "pay-1,main,2026-10-10,in,1500.00,RUB,7700000001,ООО Бета,Оплата по счёту,15,,\n"
    ).encode()
    uploaded = _upload(client, company_id, bank["id"], body, "one.csv", "i3-bank")
    assert _commit(client, uploaded.json()["id"]).status_code == 200
    other = _source(
        client,
        company_id,
        wallet_id,
        name="1С",
        type="clientbank",
        namespace="onec",
        format="clientbank",
        authoritative=False,
    )
    linked = _upload(
        client,
        company_id,
        other["id"],
        (FIXTURES / "clientbank_ok.txt").read_bytes(),
        "bank.txt",
        "i3-onec",
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["counts"]["linked"] == 1
    assert _commit(client, linked.json()["id"]).status_code == 200
    assert _tx_count(admin) == 1
    with admin.connect() as connection:
        identities = connection.execute(text("SELECT count(*) FROM source_identities")).scalar_one()
    assert identities == 2


def test_i4_changed_payload_revises_existing(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "i4@example.com")
    source = _source(client, company_id, wallet_id, namespace="bank-4")
    first_body = (HEADER + "ext-1,main,2026-10-10,out,10.00,RUB,,,аренда,1,,\n").encode()
    first = _upload(client, company_id, source["id"], first_body, "a.csv", "i4-a")
    assert _commit(client, first.json()["id"]).status_code == 200
    second_body = (HEADER + "ext-1,main,2026-10-10,out,12.00,RUB,,,аренда,1,,\n").encode()
    second = _upload(client, company_id, source["id"], second_body, "b.csv", "i4-b")
    assert second.json()["counts"]["changed"] == 1, second.text
    assert second.json()["rows"][0]["proposed_action"] == "revise"
    assert _commit(client, second.json()["id"]).status_code == 200
    assert _tx_count(admin) == 1
    with admin.connect() as connection:
        amount = connection.execute(text("SELECT amount FROM cash_transactions")).scalar_one()
        revisions = connection.execute(
            text("SELECT count(*) FROM transaction_revisions")
        ).scalar_one()
    assert str(amount) == "12.00"
    assert revisions == 1


def test_i5_invalid_rows_are_explicit(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "i5@example.com")
    source = _source(client, company_id, wallet_id, namespace="bank-5")
    uploaded = _upload(
        client,
        company_id,
        source["id"],
        (FIXTURES / "cash_bad.csv").read_bytes(),
        "bad.csv",
        "i5",
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["counts"]["invalid"] == 4, uploaded.text
    assert uploaded.json()["counts"]["new"] == 1
    committed = _commit(client, uploaded.json()["id"])
    assert committed.json()["status"] == "completed_with_errors"
    assert "partial_import" in committed.json()["quality_flags"]
    errors = client.get(f"/api/v1/imports/{uploaded.json()['id']}/errors")
    assert errors.status_code == 200
    assert "bad_date" in errors.text
    assert _tx_count(admin) == 1


def test_unknown_format_and_formula(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "fmt@example.com")
    source = _source(client, company_id, wallet_id, namespace="bank-f", format="csv")
    unknown = _upload(
        client,
        company_id,
        source["id"],
        (FIXTURES / "unknown.txt").read_bytes(),
        "notes.txt",
        "unknown",
    )
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "unsupported_format"
    sheet = _source(
        client, company_id, wallet_id, name="Таблица", namespace="xlsx", format="xlsx"
    )
    formula = _upload(
        client,
        company_id,
        sheet["id"],
        (FIXTURES / "cash_formula.xlsx").read_bytes(),
        "cash.xlsx",
        "formula",
    )
    assert formula.status_code == 200, formula.text
    assert "formula_without_value" in formula.json()["rows"][0]["errors"]
    good = _upload(
        client,
        company_id,
        sheet["id"],
        (FIXTURES / "cash_ok.xlsx").read_bytes(),
        "ok.xlsx",
        "xlsx-ok",
    )
    assert good.status_code == 200, good.text
    assert _commit(client, good.json()["id"]).status_code == 200
    assert _tx_count(admin) == 1


def test_i9_locked_classification_survives_import(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "i9@example.com")
    source = _source(client, company_id, wallet_id, namespace="bank-9")
    body = (HEADER + "ext-9,main,2026-10-10,out,10.00,RUB,,,аренда офиса,1,,\n").encode()
    uploaded = _upload(client, company_id, source["id"], body, "a.csv", "i9-a")
    committed = _commit(client, uploaded.json()["id"])
    assert committed.status_code == 200, committed.text
    listed = client.get(f"/api/v1/companies/{company_id}/transactions")
    assert listed.status_code == 200, listed.text
    assert listed.json()["transactions"], listed.text
    tx = listed.json()["transactions"][0]
    with admin.connect() as connection:
        category = connection.execute(
            text("SELECT id FROM cash_categories WHERE code = 'investing'")
        ).scalar_one()
    classified = client.post(
        f"/api/v1/transactions/{tx['id']}/classify",
        json={"version": tx["version"], "category_id": str(category)},
    )
    assert classified.status_code == 200, classified.text
    rule = client.post(
        f"/api/v1/companies/{company_id}/classification-rules",
        json={
            "name": "Аренда",
            "priority": 1,
            "conditions": {"description_contains": "аренда", "direction": "out"},
            "category_code": "operating",
        },
        headers={"Idempotency-Key": "import-api-rule-rent"},
    )
    assert rule.status_code == 200, rule.text
    preview = client.post(
        f"/api/v1/rules/{rule.json()['id']}/preview",
        json={"company_id": company_id},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["skipped_locked"] == 1
    assert preview.json()["matches"] == []
    changed = (HEADER + "ext-9,main,2026-10-10,out,15.00,RUB,,,аренда офиса,1,,\n").encode()
    again = _upload(client, company_id, source["id"], changed, "b.csv", "i9-b")
    assert _commit(client, again.json()["id"]).status_code == 200
    with admin.connect() as connection:
        row = connection.execute(
            text("SELECT amount, category_id, locked_classification FROM cash_transactions")
        ).one()
    assert str(row.amount) == "15.00"
    assert str(row.category_id) == str(category)
    assert row.locked_classification is True


def test_import_guards(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "guard-imp@example.com")
    source = _source(client, company_id, wallet_id, namespace="guard")
    content = (HEADER + "g-1,main,2026-10-10,in,5.00,RUB,,,,1,,\n").encode()
    first = _upload(client, company_id, source["id"], content, "a.csv", "same-key")
    replay = _upload(client, company_id, source["id"], content, "a.csv", "same-key")
    assert first.json()["id"] == replay.json()["id"]
    other = (HEADER + "g-2,main,2026-10-10,in,6.00,RUB,,,,1,,\n").encode()
    conflict = _upload(client, company_id, source["id"], other, "b.csv", "same-key")
    assert conflict.status_code == 409
    app.state.settings.import_max_bytes = 8
    huge = _upload(client, company_id, source["id"], b"0123456789", "big.csv", "big")
    assert huge.status_code == 413
    foreign = TestClient(app)
    _ready(foreign, admin, app, fake, tmp_path, "other-imp@example.com")
    hidden = _upload(foreign, company_id, source["id"], content, "a.csv", "foreign")
    assert hidden.status_code == 404
    end = client.get("/api/v1/billing/subscription").json()["paid_through"]
    freeze(app, datetime.fromisoformat(end) + timedelta(seconds=1))
    login(client, "guard-imp@example.com")
    memberships = client.get("/api/v1/auth/me").json()["memberships"]
    client.headers["X-Tenant-Id"] = memberships[0]["tenant_id"]
    blocked = _upload(client, company_id, source["id"], content, "a.csv", "late")
    assert blocked.status_code == 402


def test_operator_cannot_import(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "boss-imp@example.com")
    tenant = client.headers["X-Tenant-Id"]
    source = _source(client, company_id, wallet_id, namespace="op")
    invited = client.post(
        f"/api/v1/workspaces/{tenant}/invitations",
        json={"email": "op-imp@example.com", "role": "operator"},
    )
    assert invited.status_code == 200, invited.text
    token = token_from_link(latest_link(admin))
    guest = TestClient(app)
    register_and_verify(guest, admin, "op-imp@example.com", name="Оператор")
    logged = login(guest, "op-imp@example.com")
    accepted = guest.post(
        "/api/v1/auth/invitations/accept",
        json={"token": token},
    )
    assert accepted.status_code == 200, accepted.text
    guest.headers["X-Tenant-Id"] = tenant
    granted = client.post(
        f"/api/v1/workspaces/{tenant}/company-access",
        json={"user_id": logged["user"]["id"], "company_id": company_id},
    )
    assert granted.status_code == 200, granted.text
    content = (HEADER + "op-1,main,2026-10-10,in,5.00,RUB,,,,1,,\n").encode()
    denied = _upload(guest, company_id, source["id"], content, "a.csv", "op-import")
    assert denied.status_code == 403


def test_posted_import_cannot_be_deleted(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "nodelete@example.com")
    source = _source(client, company_id, wallet_id, namespace="keep")
    content = (HEADER + "k-1,main,2026-10-10,in,5.00,RUB,,,,1,,\n").encode()
    uploaded = _upload(client, company_id, source["id"], content, "a.csv", "keep")
    assert _commit(client, uploaded.json()["id"]).status_code == 200
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as connection:
        try:
            connection.execute("DELETE FROM cash_transactions")
            raised = False
        except psycopg.Error:
            raised = True
        connection.rollback()
    assert raised is True


def _board(client, company_id: str, date_from: str, date_to: str) -> dict:
    response = client.get(
        f"/api/v1/companies/{company_id}/dashboard?date_from={date_from}&date_to={date_to}"
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_dashboard_splits_balance_and_period_receipts(client, admin, app, fake, tmp_path) -> None:
    freeze(app, datetime(2026, 10, 16, 12, tzinfo=UTC))
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "board@example.com")
    opened = client.post(
        f"/api/v1/wallets/{wallet_id}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+03:00", "amount": "100000.00"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert opened.status_code == 200, opened.text
    source = _source(client, company_id, wallet_id, namespace="ucheb")
    content = (
        HEADER
        + "T-001,main,2026-10-02,in,15000.00,RUB,,Учебный покупатель,Учебное поступление,УЧ-1,,\n"
        + "T-002,main,2026-10-03,out,4000.00,RUB,,Учебный поставщик,Учебная выплата,УЧ-2,,\n"
        + "T-003,main,2026-10-06,out,2500.50,RUB,,Учебная комиссия,Учебная комиссия банка,УЧ-3,,\n"
    ).encode()
    first = _upload(client, company_id, source["id"], content, "ucheb.csv", "board-a")
    assert first.status_code == 200, first.text
    assert _commit(client, first.json()["id"]).status_code == 200
    full = _board(client, company_id, "2026-10-01", "2026-10-31")
    values = full["values"]
    assert values["opening_balance"] == "100000.00"
    assert values["cash_in"] == "15000.00"
    assert values["cash_out"] == "6500.50"
    assert values["net_cash_flow"] == "8499.50"
    assert values["cash_total"] == "108499.50"
    assert values["operation_count"] == 3
    assert values["cash_in"] != values["cash_total"]
    assert values["cash_in"] != values["opening_balance"]
    assert values["revenue"] is None
    assert full["revenue_label"] == "Нет данных о выручке"
    assert "unclassified_operations" in full["quality_flags"]
    assert "intraday_approximation" in full["quality_flags"]
    day = _board(client, company_id, "2026-10-06", "2026-10-06")["values"]
    assert day["cash_in"] == "0.00"
    assert day["cash_out"] == "2500.50"
    assert day["net_cash_flow"] == "-2500.50"
    assert day["operation_count"] == 1
    assert day["cash_total"] == "108499.50"
    assert day["opening_balance"] == "100000.00"
    second = _upload(client, company_id, source["id"], content, "ucheb.csv", "board-b")
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert _commit(client, second.json()["id"]).status_code == 200
    again = _board(client, company_id, "2026-10-01", "2026-10-31")["values"]
    assert again == values
    assert _tx_count(admin) == 3


def test_loaded_turnovers_without_opening_stay_visible(client, admin, app, fake, tmp_path) -> None:
    freeze(app, datetime(2026, 10, 16, 12, tzinfo=UTC))
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "no-open@example.com")
    source = _source(client, company_id, wallet_id, namespace="no-open")
    content = (
        HEADER
        + "T-001,main,2026-10-02,in,15000.00,RUB,,Учебный покупатель,Учебное поступление,УЧ-1,,\n"
        + "T-002,main,2026-10-03,out,4000.00,RUB,,Учебный поставщик,Учебная выплата,УЧ-2,,\n"
        + "T-003,main,2026-10-06,out,2500.50,RUB,,Учебная комиссия,Учебная комиссия банка,УЧ-3,,\n"
    ).encode()
    uploaded = _upload(client, company_id, source["id"], content, "ucheb.csv", "no-open")
    assert uploaded.status_code == 200, uploaded.text
    assert _commit(client, uploaded.json()["id"]).status_code == 200
    board = _board(client, company_id, "2026-10-01", "2026-10-31")
    values = board["values"]
    assert values["cash_in"] == "15000.00"
    assert values["cash_out"] == "6500.50"
    assert values["net_cash_flow"] == "8499.50"
    assert values["operation_count"] == 3
    assert values["opening_balance"] is None
    assert values["cash_total"] is None
    assert "missing_opening_balance" in board["quality_flags"]
    assert "missing_anchor" in board["quality_flags"]
