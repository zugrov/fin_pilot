import json
from datetime import datetime, timedelta
from decimal import Decimal
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
AS_OF = "2026-10-14"
PERIOD = "date_from=2026-10-01&date_to=2026-10-31"


def _ready(client, admin, app, fake, tmp_path, email: str, companies: int = 1) -> tuple[str, str]:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "План")
    company = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Фирма", "kind": "company"},
    )
    assert company.status_code == 200, company.text
    company_id = company.json()["id"]
    pay(client, app, fake, companies, "month")
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return tenant_id, company_id


def _wallet(client, company_id: str, amount: str, code: str = "main") -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Расчётный", "type": "bank", "code": code},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    opened = client.post(
        f"/api/v1/wallets/{created.json()['id']}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+00:00", "amount": amount},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert opened.status_code == 200, opened.text
    return created.json()


def _cash(client, company_id: str, wallet_id: str, direction: str, amount: str, day: str) -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/transactions",
        json={
            "wallet_id": wallet_id,
            "business_date": day,
            "direction": direction,
            "amount": amount,
            "description": "факт",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    return created.json()


def _event(client, company_id: str, direction: str, amount: str, day: str, **extra) -> dict:
    body = {
        "direction": direction,
        "amount": amount,
        "due_date": extra.pop("due_date", day),
        "expected_date": day,
        "confidence": extra.pop("confidence", "expected"),
    }
    body.update(extra)
    created = client.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json=body,
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    return created.json()


def _forecast(client, company_id: str, scenario: str = "base") -> dict:
    response = client.get(
        f"/api/v1/companies/{company_id}/forecast?as_of={AS_OF}&scenario={scenario}"
    )
    assert response.status_code == 200, response.text
    return response.json()


def _point(payload: dict, day: str) -> dict:
    return next(item for item in payload["points"] if item["date"] == day)


def _count(admin, table: str) -> int:
    with admin.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def test_f1_and_f4_gap_without_budget(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "f1@example.com")
    _wallet(client, company_id, "100000.00")
    _event(client, company_id, "in", "20000.00", "2026-10-15")
    _event(client, company_id, "out", "150000.00", "2026-10-15")
    payload = _forecast(client, company_id)
    assert payload["status"] == "ready"
    assert payload["opening"] == "100000.00"
    point = _point(payload, "2026-10-15")
    assert point["closing"] == "-30000.00"
    assert payload["gap_date"] == "2026-10-15"
    assert payload["gap_amount"] == "30000.00"
    assert "рисков нет" not in json.dumps(payload, ensure_ascii=False)
    assert "alerts" not in payload
    only = client.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json={
            "direction": "out",
            "amount": "100000.00",
            "due_date": "2026-11-01",
            "expected_date": "2026-11-01",
        },
        headers={"Idempotency-Key": "f4"},
    )
    assert only.status_code == 200, only.text
    later = _forecast(client, company_id)
    november = [item for item in later["contributions"] if item["date"] == "2026-11-01"]
    assert len(november) == 1
    assert november[0]["amount"] == "100000.00"


def test_f2_residual_after_match_and_void(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "f2@example.com")
    wallet = _wallet(client, company_id, "100000.00")
    paid = _cash(client, company_id, wallet["id"], "out", "40000.00", AS_OF)
    event = _event(client, company_id, "out", "100000.00", "2026-10-15")
    matched = client.post(
        "/api/v1/payment-matches",
        json={
            "company_id": company_id,
            "event_id": event["id"],
            "cash_transaction_id": paid["id"],
            "amount": "40000.00",
        },
        headers={"Idempotency-Key": "match-40"},
    )
    assert matched.status_code == 200, matched.text
    assert matched.json()["remaining"] == "60000.00"
    payload = _forecast(client, company_id)
    flow = next(item for item in payload["contributions"] if item["source_id"] == event["id"])
    assert flow["amount"] == "60000.00"
    voided = client.post(
        f"/api/v1/transactions/{paid['id']}/void",
        json={"version": paid["version"]},
    )
    assert voided.status_code == 200, voided.text
    restored = _forecast(client, company_id)
    again = next(item for item in restored["contributions"] if item["source_id"] == event["id"])
    assert again["amount"] == "100000.00"
    assert _count(admin, "payment_matches") == 1


def test_f3_company_gap_stays_when_group_is_positive(client, admin, app, fake, tmp_path) -> None:
    tenant, alpha_id = _ready(client, admin, app, fake, tmp_path, "f3@example.com", companies=2)
    beta = client.post(
        f"/api/v1/workspaces/{tenant}/companies",
        json={"name": "Бета", "kind": "company"},
    )
    assert beta.status_code == 200, beta.text
    beta_id = beta.json()["id"]
    activated = client.post(f"/api/v1/billing/companies/{beta_id}/activate")
    assert activated.status_code == 200, activated.text
    _wallet(client, alpha_id, "200000.00", "alpha")
    _wallet(client, beta_id, "0.00", "beta")
    _event(client, beta_id, "out", "50000.00", "2026-10-15")
    group = client.get(f"/api/v1/workspaces/{tenant}/forecast?as_of={AS_OF}")
    assert group.status_code == 200, group.text
    body = group.json()
    assert "alerts" not in body
    assert body["group_opening"] == "200000.00"
    risks = {item["company_id"]: item for item in body["company_risks"]}
    assert risks[beta_id]["gap_amount"] == "50000.00"
    assert risks[alpha_id]["gap_amount"] == "0.00"


def test_f5_expected_move_keeps_due_and_overdue(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "f5@example.com")
    _wallet(client, company_id, "10000.00")
    event = _event(
        client, company_id, "out", "1000.00", "2026-10-01", due_date="2026-10-01"
    )
    moved = client.patch(
        f"/api/v1/planned-cash/{event['id']}",
        json={"version": event["version"], "expected_date": "2026-10-20"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["due_date"] == "2026-10-01"
    assert moved.json()["expected_date"] == "2026-10-20"
    assert moved.json()["overdue"] is True
    payload = _forecast(client, company_id)
    flow = next(item for item in payload["contributions"] if item["source_id"] == event["id"])
    assert flow["date"] == AS_OF
    assert flow["assumption"] == "overdue_payable"


def test_f6_february_occurrence_once(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "f6@example.com")
    created = client.post(
        f"/api/v1/companies/{company_id}/recurrence-rules",
        json={
            "frequency": "monthly",
            "interval_count": 1,
            "day_of_month": 31,
            "start_date": "2026-01-31",
            "direction": "out",
            "amount": "1000.00",
            "as_of": "2026-02-01",
        },
        headers={"Idempotency-Key": "feb-rule"},
    )
    assert created.status_code == 200, created.text
    again = client.post(
        f"/api/v1/recurrence-rules/{created.json()['id']}/generate",
        json={"as_of": "2026-02-01"},
    )
    assert again.status_code == 200, again.text
    assert again.json()["created"] == 0
    calendar = client.get(f"/api/v1/companies/{company_id}/calendar")
    february = [
        item for item in calendar.json()["events"] if item["expected_date"] == "2026-02-28"
    ]
    assert len(february) == 1
    assert february[0]["due_date"] == "2026-02-28"


def test_f7_confirmed_is_not_haircut(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "f7@example.com")
    _wallet(client, company_id, "0.00")
    _event(client, company_id, "in", "100000.00", "2026-10-15", confidence="expected")
    _event(client, company_id, "in", "40000.00", "2026-10-15", confidence="confirmed")
    payload = _forecast(client, company_id, "conservative")
    amounts = {item["assumption"]: item for item in payload["contributions"]}
    assert amounts["conservative_haircut"]["amount"] == "80000.00"
    assert amounts["conservative_haircut"]["date"] == "2026-10-22"
    assert amounts["residual"]["amount"] == "40000.00"
    assert amounts["residual"]["date"] == "2026-10-15"


def test_f8_posted_fact_is_not_repeated(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "f8@example.com")
    wallet = _wallet(client, company_id, "0.00")
    _cash(client, company_id, wallet["id"], "in", "50000.00", AS_OF)
    payload = _forecast(client, company_id)
    assert payload["opening"] == "50000.00"
    assert _point(payload, AS_OF)["inflows"] == "0.00"
    assert payload["contributions"] == []


def test_a9_group_excludes_both_legs(client, admin, app, fake, tmp_path) -> None:
    tenant, alpha_id = _ready(client, admin, app, fake, tmp_path, "a9@example.com", companies=2)
    beta = client.post(
        f"/api/v1/workspaces/{tenant}/companies",
        json={"name": "Бета", "kind": "company"},
    )
    beta_id = beta.json()["id"]
    assert client.post(f"/api/v1/billing/companies/{beta_id}/activate").status_code == 200
    left = _wallet(client, alpha_id, "0.00", "alpha")
    right = _wallet(client, beta_id, "0.00", "beta")
    out_leg = _cash(client, alpha_id, left["id"], "out", "1000.00", "2026-10-10")
    in_leg = _cash(client, beta_id, right["id"], "in", "1000.00", "2026-10-10")
    linked = client.post(
        "/api/v1/transfers/link",
        json={"left_id": out_leg["id"], "right_id": in_leg["id"]},
    )
    assert linked.status_code == 200, linked.text
    alpha = client.get(f"/api/v1/companies/{alpha_id}/cash-summary")
    assert alpha.json()["external_out"] == "1000.00"
    own = client.get(f"/api/v1/companies/{alpha_id}/cashflow?{PERIOD}")
    assert _external(own.json(), "out") == "1000.00"
    both = client.get(f"/api/v1/workspaces/{tenant}/cashflow?{PERIOD}")
    assert both.status_code == 200, both.text
    assert both.json()["external_in"] == "0.00"
    assert both.json()["external_out"] == "0.00"
    assert both.json()["excluded_transfer_ids"]
    one = client.get(
        f"/api/v1/workspaces/{tenant}/cashflow?{PERIOD}&company_ids={alpha_id}"
    )
    assert one.json()["external_out"] == "1000.00"


def test_plan_import_does_not_touch_cash_or_matches(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "plan-imp@example.com")
    wallet = _wallet(client, company_id, "0.00")
    _cash(client, company_id, wallet["id"], "out", "40000.00", AS_OF)
    before = _count(admin, "cash_transactions")
    source = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "План",
            "type": "file",
            "namespace": "plan",
            "format": "csv",
            "dataset": "plan",
        },
    )
    assert source.status_code == 200, source.text
    content = (FIXTURES / "planned_ok.csv").read_bytes()
    first = _upload(client, company_id, source.json()["id"], content, "plan-file")
    assert first.status_code == 200, first.text
    assert first.json()["counts"]["new"] == 1
    committed = client.post(f"/api/v1/imports/{first.json()['id']}/commit")
    assert committed.status_code == 200, committed.text
    assert _count(admin, "cash_transactions") == before
    assert _count(admin, "planned_cash_events") == 1
    repeat = _upload(client, company_id, source.json()["id"], content, "plan-file-2")
    assert repeat.json()["id"] == first.json()["id"]
    event = client.get(f"/api/v1/companies/{company_id}/calendar").json()["events"][0]
    paid = client.get(f"/api/v1/companies/{company_id}/transactions").json()["transactions"][0]
    matched = client.post(
        "/api/v1/payment-matches",
        json={
            "company_id": company_id,
            "event_id": event["id"],
            "cash_transaction_id": paid["id"],
            "amount": "40000.00",
        },
        headers={"Idempotency-Key": "keep-match"},
    )
    assert matched.status_code == 200, matched.text
    smaller = content.replace(b"100000.00", b"1000.00")
    blocked = _upload(client, company_id, source.json()["id"], smaller, "plan-low")
    assert blocked.json()["counts"]["invalid"] == 1
    assert "amount_below_matched" in blocked.json()["rows"][0]["errors"]
    kept = client.get(f"/api/v1/companies/{company_id}/calendar").json()["events"][0]
    assert kept["amount"] == "100000.00"
    assert kept["matched"] == "40000.00"
    assert _count(admin, "payment_matches") == 1
    bad = _upload(
        client,
        company_id,
        source.json()["id"],
        (FIXTURES / "planned_bad.csv").read_bytes(),
        "plan-bad",
    )
    assert bad.status_code == 200, bad.text
    assert bad.json()["counts"]["invalid"] == 2
    assert bad.json()["counts"]["new"] == 1
    unknown = _upload(
        client,
        company_id,
        source.json()["id"],
        b"external_id,amount\n1,10\n",
        "bad-header",
    )
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "unsupported_format"


def test_obligation_is_one_event(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "debt@example.com")
    _wallet(client, company_id, "0.00")
    created = client.post(
        f"/api/v1/companies/{company_id}/obligations",
        json={
            "obligation_type": "payable",
            "issue_date": "2026-10-01",
            "due_date": "2026-10-20",
            "original_amount": "80000.00",
        },
        headers={"Idempotency-Key": "debt-1"},
    )
    assert created.status_code == 200, created.text
    payload = _forecast(client, company_id)
    assert len(payload["contributions"]) == 1
    assert payload["contributions"][0]["amount"] == "80000.00"
    assert _count(admin, "planned_cash_events") == 1
    assert _count(admin, "obligation_cash_links") == 1


def test_plan_access_guards(client, admin, app, fake, tmp_path) -> None:
    tenant, company_id = _ready(client, admin, app, fake, tmp_path, "guard-plan@example.com")
    invited = client.post(
        f"/api/v1/workspaces/{tenant}/invitations",
        json={"email": "op-plan@example.com", "role": "operator"},
    )
    assert invited.status_code == 200, invited.text
    token = token_from_link(latest_link(admin))
    guest = TestClient(app)
    register_and_verify(guest, admin, "op-plan@example.com", name="Оператор")
    logged = login(guest, "op-plan@example.com")
    assert guest.post("/api/v1/auth/invitations/accept", json={"token": token}).status_code == 200
    guest.headers["X-Tenant-Id"] = tenant
    granted = client.post(
        f"/api/v1/workspaces/{tenant}/company-access",
        json={"user_id": logged["user"]["id"], "company_id": company_id},
    )
    assert granted.status_code == 200, granted.text
    denied = guest.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json={
            "direction": "out",
            "amount": "10.00",
            "due_date": "2026-10-20",
            "expected_date": "2026-10-20",
        },
        headers={"Idempotency-Key": "op-plan"},
    )
    assert denied.status_code == 403
    foreign = TestClient(app)
    _ready(foreign, admin, app, fake, tmp_path, "other-plan@example.com")
    hidden = foreign.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json={
            "direction": "out",
            "amount": "10.00",
            "due_date": "2026-10-20",
            "expected_date": "2026-10-20",
        },
        headers={"Idempotency-Key": "foreign-plan"},
    )
    assert hidden.status_code == 404
    end = client.get("/api/v1/billing/subscription").json()["paid_through"]
    freeze(app, datetime.fromisoformat(end) + timedelta(seconds=1))
    login(client, "guard-plan@example.com")
    client.headers["X-Tenant-Id"] = client.get("/api/v1/auth/me").json()["memberships"][0][
        "tenant_id"
    ]
    blocked = client.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json={
            "direction": "out",
            "amount": "10.00",
            "due_date": "2026-10-20",
            "expected_date": "2026-10-20",
        },
        headers={"Idempotency-Key": "late-plan"},
    )
    assert blocked.status_code == 402


def _external(payload: dict, side: str) -> str:
    total = sum((Decimal(section[side]) for section in payload["sections"]), Decimal("0"))
    return f"{total:.2f}"


def _upload(client, company_id: str, connection_id: str, content: bytes, key: str):
    return client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": connection_id},
        files={"upload": ("planned_cash.csv", content, "text/csv")},
        headers={"Idempotency-Key": key},
    )
