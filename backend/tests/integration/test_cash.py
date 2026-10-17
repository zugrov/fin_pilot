import os
from datetime import UTC, datetime, timedelta
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


def _ready(client, admin, app, fake, email: str = "cash@example.com") -> tuple[str, str]:
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Касса")
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


def _wallet(client, company_id: str, name: str = "Расчётный", **extra) -> dict:
    payload = {"name": name, "type": "bank", "availability_type": "spendable"}
    key = extra.pop("idempotency_key", None)
    payload.update(extra)
    headers = {"Idempotency-Key": key or uuid4().hex}
    created = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json=payload,
        headers=headers,
    )
    assert created.status_code == 200, created.text
    return created.json()


def _anchor(client, wallet_id: str, amount: str = "100000.00", *, key: str | None = None) -> None:
    opened = client.post(
        f"/api/v1/wallets/{wallet_id}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+00:00", "amount": amount},
        headers={"Idempotency-Key": key or uuid4().hex},
    )
    assert opened.status_code == 200, opened.text


def _tx(client, company_id: str, wallet_id: str, direction: str, amount: str, **extra) -> dict:
    body = {
        "wallet_id": wallet_id,
        "business_date": "2026-10-10",
        "occurred_at": "2026-10-10T12:00:00+00:00",
        "direction": direction,
        "amount": amount,
        "description": extra.pop("description", ""),
        "status": extra.pop("status", "posted"),
    }
    body.update(extra)
    created = client.post(
        f"/api/v1/companies/{company_id}/transactions",
        json=body,
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    return created.json()


def _category(admin, tenant_id: str, code: str) -> str:
    with admin.connect() as connection:
        found = connection.execute(
            text(
                "SELECT id FROM cash_categories WHERE tenant_id = :tenant AND code = :code"
            ),
            {"tenant": tenant_id, "code": code},
        ).scalar_one()
    return str(found)


def test_a1_posted_movements_and_void(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake)
    wallet = _wallet(client, company_id)
    assert wallet["balance"] is None
    assert "missing_anchor" in wallet["quality_flags"]
    _anchor(client, wallet["id"])
    incoming = _tx(client, company_id, wallet["id"], "in", "50000.00")
    _tx(client, company_id, wallet["id"], "out", "20000.00")
    noise = _tx(client, company_id, wallet["id"], "in", "999.00")
    voided = client.post(
        f"/api/v1/transactions/{noise['id']}/void",
        json={"version": noise["version"]},
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "void"
    summary = client.get(f"/api/v1/companies/{company_id}/cash-summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["cash_total"] == "130000.00"
    assert body["revenue"] is None
    assert "missing_revenue_source" in body["quality_flags"]
    with admin.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM cash_transactions")).scalar_one()
    assert count == 3
    assert incoming["amount"] == "50000.00"


def test_a8_missing_anchor_is_unavailable(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "anchor@example.com")
    _wallet(client, company_id)
    dashboard = client.get(f"/api/v1/companies/{company_id}/dashboard")
    assert dashboard.status_code == 200
    values = dashboard.json()["values"]
    assert values["cash_total"] is None
    assert values["opening_balance"] is None
    assert values["cash_in"] is None
    assert values["cash_out"] is None
    assert values["net_cash_flow"] is None
    assert values["operation_count"] is None
    assert values["revenue"] is None
    assert "missing_anchor" in dashboard.json()["quality_flags"]


def test_a2_internal_transfer_is_not_external_turnover(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "transfer@example.com")
    left = _wallet(client, company_id, "Левый")
    right = _wallet(client, company_id, "Правый")
    _anchor(client, left["id"], "100000.00")
    _anchor(client, right["id"], "0.00")
    out_leg = _tx(client, company_id, left["id"], "out", "30000.00")
    in_leg = _tx(client, company_id, right["id"], "in", "30000.00")
    linked = client.post(
        "/api/v1/transfers/link",
        json={"left_id": out_leg["id"], "right_id": in_leg["id"]},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["kind"] == "internal"
    summary = client.get(f"/api/v1/companies/{company_id}/cash-summary").json()
    assert summary["cash_total"] == "100000.00"
    assert summary["external_in"] == "0.00"
    assert summary["external_out"] == "0.00"
    board = client.get(
        f"/api/v1/companies/{company_id}/dashboard?date_from=2026-10-01&date_to=2026-10-31"
    ).json()["values"]
    assert board["cash_in"] == "0.00"
    assert board["cash_out"] == "0.00"
    assert board["cash_total"] == "100000.00"
    assert board["opening_balance"] == "100000.00"
    assert board["cash_in"] != board["cash_total"]


def test_opening_balance_is_not_a_receipt(client, admin, app, fake) -> None:
    freeze(app, datetime(2026, 10, 16, 12, tzinfo=UTC))
    _tenant, company_id = _ready(client, admin, app, fake, "opening-not-in@example.com")
    wallet = _wallet(client, company_id)
    _anchor(client, wallet["id"], "100000.00")
    values = client.get(
        f"/api/v1/companies/{company_id}/dashboard?date_from=2026-10-01&date_to=2026-10-31"
    ).json()["values"]
    assert values["opening_balance"] == "100000.00"
    assert values["cash_total"] == "100000.00"
    assert values["cash_in"] == "0.00"
    assert values["cash_out"] == "0.00"
    assert values["net_cash_flow"] == "0.00"
    assert values["operation_count"] == 0
    assert values["cash_in"] != values["cash_total"]
    assert values["revenue"] is None


def test_a3_owner_contribution_is_financing(client, admin, app, fake) -> None:
    tenant, company_id = _ready(client, admin, app, fake, "owner-cash@example.com")
    wallet = _wallet(client, company_id)
    _anchor(client, wallet["id"], "0.00")
    category = _category(admin, tenant, "owner_contribution")
    _tx(
        client,
        company_id,
        wallet["id"],
        "in",
        "100000.00",
        category_id=category,
    )
    summary = client.get(f"/api/v1/companies/{company_id}/cash-summary").json()
    assert summary["cash_total"] == "100000.00"
    assert summary["financing_in"] == "100000.00"
    assert summary["revenue"] is None


def test_a7_restricted_and_reserve(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "reserve@example.com")
    spendable = _wallet(client, company_id, "Свободный")
    locked = _wallet(
        client,
        company_id,
        "Депозит",
        type="deposit",
        availability_type="restricted",
    )
    _anchor(client, spendable["id"], "200000.00")
    _anchor(client, locked["id"], "100000.00")
    reserve = client.patch(
        f"/api/v1/companies/{company_id}",
        json={"min_cash_reserve": "50000.00"},
    )
    assert reserve.status_code == 200, reserve.text
    summary = client.get(f"/api/v1/companies/{company_id}/cash-summary").json()
    assert summary["cash_total"] == "300000.00"
    assert summary["available"] == "200000.00"
    assert summary["restricted"] == "100000.00"
    assert summary["headroom"] == "150000.00"


def test_version_conflict_and_classify(client, admin, app, fake) -> None:
    tenant, company_id = _ready(client, admin, app, fake, "version@example.com")
    wallet = _wallet(client, company_id)
    _anchor(client, wallet["id"], "1000.00")
    row = _tx(client, company_id, wallet["id"], "out", "10.00")
    stale = client.patch(
        f"/api/v1/transactions/{row['id']}",
        json={"version": row["version"] + 5, "description": "позже"},
    )
    assert stale.status_code == 409
    category = _category(admin, tenant, "operating")
    classified = client.post(
        f"/api/v1/transactions/{row['id']}/classify",
        json={"version": row["version"], "category_id": category},
    )
    assert classified.status_code == 200, classified.text
    assert classified.json()["locked_classification"] is True
    again = client.patch(
        f"/api/v1/transactions/{row['id']}",
        json={"version": row["version"], "amount": "11.00"},
    )
    assert again.status_code == 409


def test_foreign_wallet_is_hidden(client, admin, app, fake) -> None:
    _ready(client, admin, app, fake, "home@example.com")
    other = TestClient(app)
    _tenant, company_id = _ready(other, admin, app, fake, "away@example.com")
    wallet = _wallet(other, company_id)
    hidden = client.get(f"/api/v1/companies/{company_id}/wallets")
    assert hidden.status_code == 404
    missing = client.post(
        f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+00:00", "amount": "1.00"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert missing.status_code == 404


def test_operator_wallet_access_and_no_analytics(client, admin, app, fake) -> None:
    tenant, company_id = _ready(client, admin, app, fake, "boss@example.com")
    wallet = _wallet(client, company_id)
    _anchor(client, wallet["id"], "1000.00")
    row = _tx(client, company_id, wallet["id"], "in", "10.00")
    invited = client.post(
        f"/api/v1/workspaces/{tenant}/invitations",
        json={"email": "op@example.com", "role": "operator"},
    )
    assert invited.status_code == 200, invited.text
    token = token_from_link(latest_link(admin))
    guest = TestClient(app)
    register_and_verify(guest, admin, "op@example.com", name="Оператор")
    logged = login(guest, "op@example.com")
    accepted = guest.post("/api/v1/auth/invitations/accept", json={"token": token})
    assert accepted.status_code == 200, accepted.text
    guest.headers["X-Tenant-Id"] = tenant
    user_id = logged["user"]["id"]
    granted_company = client.post(
        f"/api/v1/workspaces/{tenant}/company-access",
        json={"user_id": user_id, "company_id": company_id},
    )
    assert granted_company.status_code == 200, granted_company.text
    denied = guest.get(f"/api/v1/transactions/{row['id']}")
    assert denied.status_code == 404
    analytics = guest.get(f"/api/v1/companies/{company_id}/cash-summary")
    assert analytics.status_code == 403
    group = guest.get(f"/api/v1/workspaces/{tenant}/group-summary")
    assert group.status_code == 403
    created = guest.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Нет", "type": "cash"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 403
    access = client.post(
        f"/api/v1/wallets/{wallet['id']}/access",
        json={"user_id": user_id, "can_read": True, "can_create": True},
    )
    assert access.status_code == 200, access.text
    visible = guest.get(f"/api/v1/transactions/{row['id']}")
    assert visible.status_code == 200, visible.text
    own = guest.post(
        f"/api/v1/companies/{company_id}/transactions",
        json={
            "wallet_id": wallet["id"],
            "business_date": "2026-10-11",
            "occurred_at": "2026-10-11T12:00:00+00:00",
            "direction": "out",
            "amount": "1.00",
        },
        headers={"Idempotency-Key": "operator-create"},
    )
    assert own.status_code == 200, own.text


def test_write_after_paid_through_is_402(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "late@example.com")
    wallet = _wallet(client, company_id)
    end = datetime.fromisoformat(client.get("/api/v1/billing/subscription").json()["paid_through"])
    freeze(app, end + timedelta(seconds=1))
    login(client, "late@example.com")
    client.headers["X-Tenant-Id"] = _tenant
    blocked = client.post(
        f"/api/v1/companies/{company_id}/transactions",
        json={
            "wallet_id": wallet["id"],
            "business_date": "2026-11-20",
            "direction": "in",
            "amount": "1.00",
        },
        headers={"Idempotency-Key": "after-paid"},
    )
    assert blocked.status_code == 402


def test_posted_change_without_revision_is_rejected(client, admin, app, fake) -> None:
    tenant, company_id = _ready(client, admin, app, fake, "guard@example.com")
    wallet = _wallet(client, company_id)
    _anchor(client, wallet["id"], "100.00")
    row = _tx(client, company_id, wallet["id"], "in", "5.00")
    url = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant,))
        connection.execute("SELECT set_config('app.user_id', %s, true)", (str(uuid4()),))
        try:
            connection.execute(
                "UPDATE cash_transactions SET amount = 6 WHERE id = %s",
                (row["id"],),
            )
            raised = False
        except psycopg.Error:
            raised = True
        connection.rollback()
    assert raised is True


def test_intercompany_transfer_is_shown_on_each_company(client, admin, app, fake) -> None:
    register_and_verify(client, admin, "group@example.com")
    login(client, "group@example.com")
    tenant_id = open_workspace(client, "Группа")
    first = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Альфа", "kind": "company"},
    )
    second = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Бета", "kind": "company"},
    )
    assert first.status_code == second.status_code == 200
    pay(client, app, fake, 2, "month")
    for company in (first.json(), second.json()):
        activated = client.post(f"/api/v1/billing/companies/{company['id']}/activate")
        assert activated.status_code == 200, activated.text
    left = _wallet(client, first.json()["id"], "Альфа")
    right = _wallet(client, second.json()["id"], "Бета")
    _anchor(client, left["id"], "0.00")
    _anchor(client, right["id"], "0.00")
    out_leg = _tx(client, first.json()["id"], left["id"], "out", "1000.00")
    in_leg = _tx(client, second.json()["id"], right["id"], "in", "1000.00")
    linked = client.post(
        "/api/v1/transfers/link",
        json={"left_id": out_leg["id"], "right_id": in_leg["id"]},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["kind"] == "intercompany"
    alpha = client.get(f"/api/v1/companies/{first.json()['id']}/cash-summary").json()
    beta = client.get(f"/api/v1/companies/{second.json()['id']}/cash-summary").json()
    assert alpha["external_out"] == "1000.00"
    assert beta["external_in"] == "1000.00"
    assert alpha["cash_total"] == "-1000.00"
    assert beta["cash_total"] == "1000.00"
    group = client.get(f"/api/v1/workspaces/{tenant_id}/group-summary").json()
    assert group["metrics"]["cash_total"] == "0.00"
    assert group["metrics"]["revenue"] is None


def test_idempotent_create_replays_same_body(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "idem@example.com")
    wallet = _wallet(client, company_id)
    body = {
        "wallet_id": wallet["id"],
        "business_date": "2026-10-10",
        "direction": "in",
        "amount": "15.00",
        "status": "draft",
    }
    headers = {"Idempotency-Key": "same-cash-key"}
    created = client.post(
        f"/api/v1/companies/{company_id}/transactions", json=body, headers=headers
    )
    replay = client.post(
        f"/api/v1/companies/{company_id}/transactions", json=body, headers=headers
    )
    assert created.status_code == replay.status_code == 200
    assert created.json()["id"] == replay.json()["id"]
    changed = dict(body)
    changed["amount"] = "16.00"
    conflict = client.post(
        f"/api/v1/companies/{company_id}/transactions", json=changed, headers=headers
    )
    assert conflict.status_code == 409
    summary = client.get(f"/api/v1/companies/{company_id}/cash-summary").json()
    assert summary["cash_total"] is None
