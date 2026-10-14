from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

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
PERIOD = "date_from=2026-10-01&date_to=2026-10-31"


def _ready(client, admin, app, fake, tmp_path, email: str) -> tuple[str, str]:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Выручка")
    company = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Фирма", "kind": "company"},
    )
    assert company.status_code == 200, company.text
    company_id = company.json()["id"]
    pay(client, app, fake, 1, "month")
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return tenant_id, company_id


def _wallet(client, company_id: str) -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Расчётный", "type": "bank", "code": "main"},
    )
    assert created.status_code == 200, created.text
    opened = client.post(
        f"/api/v1/wallets/{created.json()['id']}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+00:00", "amount": "0.00"},
    )
    assert opened.status_code == 200, opened.text
    return created.json()


def _cash(client, company_id: str, wallet_id: str, direction: str, amount: str, **extra) -> dict:
    body = {
        "wallet_id": wallet_id,
        "business_date": extra.pop("business_date", "2026-10-10"),
        "direction": direction,
        "amount": amount,
        "description": extra.pop("description", "оплата"),
    }
    body.update(extra)
    created = client.post(
        f"/api/v1/companies/{company_id}/transactions",
        json=body,
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    return created.json()


def _sale(client, company_id: str, key: str) -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-10",
            "document_number": "15",
            "amount_ex_vat": "100000.00",
            "vat_amount": "20000.00",
            "amount_inc_vat": "120000.00",
            "entry_type": "sale",
            "vat_basis": "net",
        },
        headers={"Idempotency-Key": key},
    )
    assert created.status_code == 200, created.text
    return created.json()


def _dashboard(client, company_id: str) -> dict:
    response = client.get(f"/api/v1/companies/{company_id}/dashboard?{PERIOD}")
    assert response.status_code == 200, response.text
    return response.json()


def _entries(admin) -> int:
    with admin.connect() as connection:
        return int(connection.execute(text("SELECT count(*) FROM revenue_entries")).scalar_one())


def test_a4_advance_is_not_revenue(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "a4@example.com")
    wallet = _wallet(client, company_id)
    _cash(client, company_id, wallet["id"], "in", "60000.00")
    assert _entries(admin) == 0
    before = _dashboard(client, company_id)
    assert before["values"]["cash_total"] == "60000.00"
    assert before["values"]["revenue"] is None
    assert before["revenue_label"] == "Нет данных о выручке"
    source = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Продажи",
            "type": "file",
            "namespace": "sales",
            "format": "csv",
            "dataset": "revenue",
        },
    )
    assert source.status_code == 200, source.text
    covered = client.post(
        f"/api/v1/companies/{company_id}/sources/{source.json()['id']}/coverage",
        json={"coverage_through": "2026-10-31"},
    )
    assert covered.status_code == 200, covered.text
    after = _dashboard(client, company_id)
    assert after["values"]["cash_total"] == "60000.00"
    assert after["values"]["revenue"] == "0.00"
    assert after["values"]["revenue"] != after["values"]["cash_total"]


def test_a5_sale_and_payment_stay_separate(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "a5@example.com")
    wallet = _wallet(client, company_id)
    payment = _cash(client, company_id, wallet["id"], "in", "60000.00")
    sale = _sale(client, company_id, "a5-sale")
    body = _dashboard(client, company_id)
    assert body["values"]["revenue"] == "100000.00"
    assert body["values"]["cash_total"] == "60000.00"
    assert sale["id"] in body["drilldown_refs"]["revenue_entry_ids"]
    matched = client.post(
        "/api/v1/revenue-cash-matches",
        json={
            "company_id": company_id,
            "revenue_entry_id": sale["id"],
            "cash_transaction_id": payment["id"],
            "amount": "60000.00",
        },
        headers={"Idempotency-Key": "a5-match"},
    )
    assert matched.status_code == 200, matched.text
    again = _dashboard(client, company_id)
    assert again["values"]["revenue"] == "100000.00"
    assert again["values"]["cash_total"] == "60000.00"


def test_a6_missing_sales_source_is_not_cash_in(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "a6@example.com")
    wallet = _wallet(client, company_id)
    _cash(client, company_id, wallet["id"], "in", "60000.00")
    body = _dashboard(client, company_id)
    assert body["values"]["revenue"] is None
    assert body["values"]["revenue"] != body["values"]["cash_total"]
    assert "missing_revenue_source" in body["quality_flags"]


def test_financing_and_transfer_do_not_create_sales(client, admin, app, fake, tmp_path) -> None:
    tenant, company_id = _ready(client, admin, app, fake, tmp_path, "mix@example.com")
    left = _wallet(client, company_id)
    right = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Касса", "type": "cash", "code": "till"},
    )
    assert right.status_code == 200, right.text
    opened = client.post(
        f"/api/v1/wallets/{right.json()['id']}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+00:00", "amount": "0.00"},
    )
    assert opened.status_code == 200, opened.text
    with admin.connect() as connection:
        owner = connection.execute(
            text(
                "SELECT id FROM cash_categories "
                "WHERE tenant_id = :tenant AND code = 'owner_contribution'"
            ),
            {"tenant": tenant},
        ).scalar_one()
        loan = connection.execute(
            text("SELECT id FROM cash_categories WHERE tenant_id = :tenant AND code = 'loan'"),
            {"tenant": tenant},
        ).scalar_one()
    _cash(client, company_id, left["id"], "in", "100000.00", category_id=str(owner))
    _cash(client, company_id, left["id"], "in", "50000.00", category_id=str(loan))
    out_leg = _cash(client, company_id, left["id"], "out", "30000.00", description="перевод")
    in_leg = _cash(
        client, company_id, right.json()["id"], "in", "30000.00", description="перевод"
    )
    linked = client.post(
        "/api/v1/transfers/link",
        json={"left_id": out_leg["id"], "right_id": in_leg["id"]},
    )
    assert linked.status_code == 200, linked.text
    assert _entries(admin) == 0
    flow = client.get(f"/api/v1/companies/{company_id}/cashflow?{PERIOD}")
    assert flow.status_code == 200, flow.text
    assert flow.json()["sections"][0]["code"] == "operating"
    moved = sum(len(item["transaction_ids"]) for item in flow.json()["sections"])
    assert moved == 2


def test_revenue_csv_dedup_and_unknown_format(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "csv-rev@example.com")
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
    content = (FIXTURES / "revenue_ok.csv").read_bytes()
    first = _upload(client, company_id, source.json()["id"], content, "rev-1")
    assert first.status_code == 200, first.text
    committed = client.post(f"/api/v1/imports/{first.json()['id']}/commit")
    assert committed.status_code == 200, committed.text
    assert _entries(admin) == 1
    second = _upload(client, company_id, source.json()["id"], content, "rev-2")
    assert second.json()["id"] == first.json()["id"]
    client.post(f"/api/v1/imports/{second.json()['id']}/commit")
    assert _entries(admin) == 1
    cash_file = (FIXTURES / "cash_ok.csv").read_bytes()
    rejected = _upload(client, company_id, source.json()["id"], cash_file, "cash-on-sales")
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "unsupported_format"
    bad = _upload(
        client,
        company_id,
        source.json()["id"],
        (FIXTURES / "revenue_bad.csv").read_bytes(),
        "bad-rev",
    )
    assert bad.status_code == 200, bad.text
    assert bad.json()["counts"]["invalid"] == 2
    assert bad.json()["counts"]["new"] == 1


def test_revenue_guards(client, admin, app, fake, tmp_path) -> None:
    tenant, company_id = _ready(client, admin, app, fake, tmp_path, "guard-rev@example.com")
    first = _sale(client, company_id, "same-sale")
    replay = _sale(client, company_id, "same-sale")
    assert first["id"] == replay["id"]
    invited = client.post(
        f"/api/v1/workspaces/{tenant}/invitations",
        json={"email": "op-rev@example.com", "role": "operator"},
    )
    assert invited.status_code == 200, invited.text
    token = token_from_link(latest_link(admin))
    guest = TestClient(app)
    register_and_verify(guest, admin, "op-rev@example.com", name="Оператор")
    logged = login(guest, "op-rev@example.com")
    accepted = guest.post("/api/v1/auth/invitations/accept", json={"token": token})
    assert accepted.status_code == 200, accepted.text
    guest.headers["X-Tenant-Id"] = tenant
    granted = client.post(
        f"/api/v1/workspaces/{tenant}/company-access",
        json={"user_id": logged["user"]["id"], "company_id": company_id},
    )
    assert granted.status_code == 200, granted.text
    denied = guest.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-10",
            "amount_inc_vat": "10.00",
            "amount_ex_vat": "10.00",
            "vat_amount": "0.00",
            "entry_type": "sale",
        },
        headers={"Idempotency-Key": "op-sale"},
    )
    assert denied.status_code == 403
    foreign = TestClient(app)
    _ready(foreign, admin, app, fake, tmp_path, "other-rev@example.com")
    hidden = foreign.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-10",
            "amount_inc_vat": "10.00",
            "amount_ex_vat": "10.00",
            "vat_amount": "0.00",
            "entry_type": "sale",
        },
        headers={"Idempotency-Key": "foreign-sale"},
    )
    assert hidden.status_code == 404
    end = client.get("/api/v1/billing/subscription").json()["paid_through"]
    freeze(app, datetime.fromisoformat(end) + timedelta(seconds=1))
    login(client, "guard-rev@example.com")
    memberships = client.get("/api/v1/auth/me").json()["memberships"]
    client.headers["X-Tenant-Id"] = memberships[0]["tenant_id"]
    blocked = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-12",
            "amount_inc_vat": "10.00",
            "amount_ex_vat": "10.00",
            "vat_amount": "0.00",
            "entry_type": "sale",
        },
        headers={"Idempotency-Key": "late-sale"},
    )
    assert blocked.status_code == 402


def _upload(client, company_id: str, connection_id: str, content: bytes, key: str):
    return client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": connection_id},
        files={"upload": ("revenue.csv", content, "text/csv")},
        headers={"Idempotency-Key": key},
    )
