import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

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
REPORT = "2026-10-31"
AS_OF = "2026-10-14"


def _ready(client, admin, app, fake, tmp_path, email: str) -> tuple[str, str]:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Бюджет")
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


def _wallet(client, company_id: str, amount: str) -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Расчётный", "type": "bank", "code": "main"},
    )
    assert created.status_code == 200, created.text
    opened = client.post(
        f"/api/v1/wallets/{created.json()['id']}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+00:00", "amount": amount},
    )
    assert opened.status_code == 200, opened.text
    return created.json()


def _cash(client, company_id: str, wallet_id: str, direction: str, amount: str, day: str, **extra):
    body = {
        "wallet_id": wallet_id,
        "business_date": day,
        "direction": direction,
        "amount": amount,
        "description": "факт",
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
            text("SELECT id FROM cash_categories WHERE tenant_id = :tenant AND code = :code"),
            {"tenant": tenant_id, "code": code},
        ).scalar_one()
    return str(found)


def _budget(client, company_id: str, basis: str, metric: str, amount: str, month: int = 10) -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/budgets",
        json={
            "name": "Год",
            "year": 2026,
            "basis": basis,
            "lines": [{"month": month, "metric_type": metric, "amount": amount}],
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    approved = client.post(
        f"/api/v1/budgets/{created.json()['id']}/approve",
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def _fact(client, company_id: str, basis: str) -> dict:
    response = client.get(
        f"/api/v1/companies/{company_id}/plan-fact?report_date={REPORT}"
    )
    assert response.status_code == 200, response.text
    return next(item for item in response.json()["bases"] if item["basis"] == basis)


def _alerts(client, company_id: str, _day: str = REPORT) -> dict:
    response = client.post(f"/api/v1/companies/{company_id}/alerts/recalculate")
    assert response.status_code == 200, response.text
    return response.json()


def _preview(client, company_id: str, day: str) -> dict:
    response = client.get(f"/api/v1/companies/{company_id}/alerts/preview?report_date={day}")
    assert response.status_code == 200, response.text
    return response.json()


def _count(admin, table: str) -> int:
    with admin.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def test_b1_deviation_does_not_cross_the_alert_threshold(
    client, admin, app, fake, tmp_path
) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "b1@example.com")
    wallet = _wallet(client, company_id, "200000.00")
    missing = client.get(f"/api/v1/companies/{company_id}/plan-fact?report_date={REPORT}")
    assert missing.json()["quality_flags"] == ["missing_budget"]
    assert _fact(client, company_id, "cash")["status"] == "unavailable"
    _cash(client, company_id, wallet["id"], "out", "120000.00", "2026-10-15")
    _budget(client, company_id, "cash", "cash_out", "100000.00")
    line = _fact(client, company_id, "cash")["lines"][0]
    assert line["plan_to_date"] == "100000.00"
    assert line["fact"] == "120000.00"
    assert line["delta"] == "20000.00"
    assert line["percent"] == "20.00"
    assert line["character"] == "adverse"
    alerts = _preview(client, company_id, REPORT)
    assert all(item["type"] != "expense_overrun" for item in alerts["alerts"])
    assert "рисков нет" not in json.dumps(alerts, ensure_ascii=False)


def test_b2_zero_plan_with_fact_is_outside_budget(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "b2@example.com")
    wallet = _wallet(client, company_id, "100000.00")
    _cash(client, company_id, wallet["id"], "out", "10000.00", "2026-10-15")
    _budget(client, company_id, "cash", "cash_out", "0.00")
    line = _fact(client, company_id, "cash")["lines"][0]
    assert line["percent"] is None
    assert line["status"] == "вне бюджета"


def test_b3_allocations_match_the_line(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "b3@example.com")
    created = client.post(
        f"/api/v1/companies/{company_id}/budgets",
        json={
            "name": "Копейки",
            "year": 2026,
            "basis": "cash",
            "lines": [{"month": 10, "metric_type": "cash_out", "amount": "100.00"}],
        },
        headers={"Idempotency-Key": "b3"},
    )
    assert created.status_code == 200, created.text
    line = created.json()["lines"][0]
    assert line["allocated_total"] == "100.00"


def test_b4_revenue_budget_uses_net_not_receipts(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "b4@example.com")
    wallet = _wallet(client, company_id, "100000.00")
    _cash(client, company_id, wallet["id"], "in", "96000.00", "2026-10-15")
    sale = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-15",
            "amount_ex_vat": "80000.00",
            "vat_amount": "16000.00",
            "amount_inc_vat": "96000.00",
            "entry_type": "sale",
            "vat_basis": "net",
        },
        headers={"Idempotency-Key": "sale-b4"},
    )
    assert sale.status_code == 200, sale.text
    _budget(client, company_id, "revenue", "revenue", "100000.00")
    line = _fact(client, company_id, "revenue")["lines"][0]
    assert line["fact"] == "80000.00"
    assert line["fact"] != "96000.00"
    unknown = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-16",
            "amount_inc_vat": "1000.00",
            "entry_type": "sale",
            "vat_basis": "unknown",
        },
        headers={"Idempotency-Key": "unknown-b4"},
    )
    assert unknown.status_code == 200, unknown.text
    hidden = _fact(client, company_id, "revenue")["lines"][0]
    assert hidden["status"] == "unavailable"
    assert hidden["fact"] is None
    alerts = _preview(client, company_id, REPORT)
    assert all(item["type"] != "revenue_shortfall" for item in alerts["alerts"])


def test_f4_budget_does_not_enter_the_forecast(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "f4b@example.com")
    _wallet(client, company_id, "100000.00")
    _budget(client, company_id, "cash", "cash_out", "100000.00")
    event = client.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json={
            "direction": "out",
            "amount": "100000.00",
            "due_date": "2026-11-01",
            "expected_date": "2026-11-01",
        },
        headers={"Idempotency-Key": "f4-event"},
    )
    assert event.status_code == 200, event.text
    forecast = client.get(f"/api/v1/companies/{company_id}/forecast?as_of={AS_OF}&scenario=base")
    assert forecast.status_code == 200, forecast.text
    body = forecast.json()
    november = [item for item in body["contributions"] if item["date"] == "2026-11-01"]
    assert len(november) == 1
    assert november[0]["amount"] == "100000.00"
    assert "alerts" not in body


def test_n1_unusual_payment_needs_ten_priors(client, admin, app, fake, tmp_path) -> None:
    tenant, company_id = _ready(client, admin, app, fake, tmp_path, "n1@example.com")
    wallet = _wallet(client, company_id, "1000000.00")
    category = _category(admin, tenant, "operating")
    for day in range(1, 11):
        _cash(
            client,
            company_id,
            wallet["id"],
            "out",
            "10000.00",
            f"2026-09-{day:02d}",
            category_id=category,
        )
    _cash(
        client,
        company_id,
        wallet["id"],
        "out",
        "50000.00",
        AS_OF,
        category_id=category,
    )
    alerts = _alerts(client, company_id, AS_OF)
    unusual = [item for item in alerts["alerts"] if item["type"] == "unusual_outgoing"]
    assert len(unusual) == 1
    assert unusual[0]["evidence"]["median"] == "10000.00"
    assert unusual[0]["status"] == "open"


def test_n2_short_history_is_not_a_statistical_alert(client, admin, app, fake, tmp_path) -> None:
    tenant, company_id = _ready(client, admin, app, fake, tmp_path, "n2@example.com")
    wallet = _wallet(client, company_id, "1000000.00")
    category = _category(admin, tenant, "operating")
    for day in range(1, 4):
        _cash(
            client,
            company_id,
            wallet["id"],
            "out",
            "10000.00",
            f"2026-09-{day:02d}",
            category_id=category,
        )
    _cash(client, company_id, wallet["id"], "out", "50000.00", AS_OF, category_id=category)
    alerts = _alerts(client, company_id, AS_OF)
    assert all(item["type"] != "unusual_outgoing" for item in alerts["alerts"])
    assert any(item["reason"] == "insufficient_history" for item in alerts["skipped"])


def test_n3_recalculation_updates_one_alert(client, admin, app, fake, tmp_path) -> None:
    tenant, company_id = _ready(client, admin, app, fake, tmp_path, "n3@example.com")
    wallet = _wallet(client, company_id, "1000000.00")
    category = _category(admin, tenant, "operating")
    for day in range(1, 11):
        _cash(
            client,
            company_id,
            wallet["id"],
            "out",
            "10000.00",
            f"2026-09-{day:02d}",
            category_id=category,
        )
    current = _cash(
        client, company_id, wallet["id"], "out", "50000.00", AS_OF, category_id=category
    )
    first = _alerts(client, company_id, AS_OF)
    second = _alerts(client, company_id, AS_OF)
    chosen = [item for item in second["alerts"] if item["type"] == "unusual_outgoing"]
    assert len(chosen) == 1
    assert chosen[0]["id"] == next(
        item["id"] for item in first["alerts"] if item["type"] == "unusual_outgoing"
    )
    assert _count(admin, "alerts") == len(second["alerts"])
    acked = client.post(f"/api/v1/alerts/{chosen[0]['id']}/ack")
    assert acked.status_code == 200, acked.text
    assert acked.json()["status"] == "acknowledged"
    again = _alerts(client, company_id, AS_OF)
    kept = next(item for item in again["alerts"] if item["id"] == chosen[0]["id"])
    assert kept["status"] == "acknowledged"
    voided = client.post(
        f"/api/v1/transactions/{current['id']}/void",
        json={"version": current["version"]},
    )
    assert voided.status_code == 200, voided.text
    resolved = _alerts(client, company_id, AS_OF)
    closed = next(item for item in resolved["alerts"] if item["id"] == chosen[0]["id"])
    assert closed["status"] == "resolved"


def test_budget_import_does_not_approve_or_create_cash(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "bimp@example.com")
    before_cash = _count(admin, "cash_transactions")
    before_plan = _count(admin, "planned_cash_events")
    source = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Бюджет",
            "type": "file",
            "namespace": "budget",
            "format": "csv",
            "dataset": "budget",
        },
    )
    assert source.status_code == 200, source.text
    content = (FIXTURES / "budget_ok.csv").read_bytes()
    first = _upload(client, company_id, source.json()["id"], content, "budget-file")
    assert first.status_code == 200, first.text
    assert first.json()["counts"]["new"] == 1
    committed = client.post(f"/api/v1/imports/{first.json()['id']}/commit")
    assert committed.status_code == 200, committed.text
    assert _count(admin, "cash_transactions") == before_cash
    assert _count(admin, "planned_cash_events") == before_plan
    budgets = client.get(f"/api/v1/companies/{company_id}/budgets")
    assert budgets.json()["budgets"][0]["status"] == "draft"
    repeat = _upload(client, company_id, source.json()["id"], content, "budget-file-2")
    assert repeat.json()["id"] == first.json()["id"]
    bad = (FIXTURES / "budget_bad.csv").read_bytes()
    preview = _upload(client, company_id, source.json()["id"], bad, "budget-bad")
    assert preview.status_code == 200, preview.text
    assert preview.json()["counts"]["invalid"] == 2
    assert preview.json()["counts"]["new"] == 1
    rejected = _upload(
        client,
        company_id,
        source.json()["id"],
        b"external_id,amount\n1,10\n",
        "budget-unknown",
    )
    assert rejected.status_code == 422
    assert rejected.json()["code"] == "unsupported_format"


def test_budget_access_guards(client, admin, app, fake, tmp_path) -> None:
    tenant, company_id = _ready(client, admin, app, fake, tmp_path, "guard-b@example.com")
    invited = client.post(
        f"/api/v1/workspaces/{tenant}/invitations",
        json={"email": "op-b@example.com", "role": "operator"},
    )
    assert invited.status_code == 200, invited.text
    token = token_from_link(latest_link(admin))
    guest = TestClient(app)
    register_and_verify(guest, admin, "op-b@example.com", name="Оператор")
    logged = login(guest, "op-b@example.com")
    assert guest.post("/api/v1/auth/invitations/accept", json={"token": token}).status_code == 200
    guest.headers["X-Tenant-Id"] = tenant
    granted = client.post(
        f"/api/v1/workspaces/{tenant}/company-access",
        json={"user_id": logged["user"]["id"], "company_id": company_id},
    )
    assert granted.status_code == 200, granted.text
    denied = guest.post(
        f"/api/v1/companies/{company_id}/budgets",
        json={
            "name": "Нет",
            "year": 2026,
            "basis": "cash",
            "lines": [{"month": 10, "metric_type": "cash_out", "amount": "1.00"}],
        },
        headers={"Idempotency-Key": "op-budget"},
    )
    assert denied.status_code == 403
    foreign = TestClient(app)
    _ready(foreign, admin, app, fake, tmp_path, "other-b@example.com")
    hidden = foreign.post(
        f"/api/v1/companies/{company_id}/budgets",
        json={
            "name": "Чужой",
            "year": 2026,
            "basis": "cash",
            "lines": [{"month": 10, "metric_type": "cash_out", "amount": "1.00"}],
        },
        headers={"Idempotency-Key": "foreign-budget"},
    )
    assert hidden.status_code == 404
    end = client.get("/api/v1/billing/subscription").json()["paid_through"]
    freeze(app, datetime.fromisoformat(end) + timedelta(seconds=1))
    login(client, "guard-b@example.com")
    client.headers["X-Tenant-Id"] = client.get("/api/v1/auth/me").json()["memberships"][0][
        "tenant_id"
    ]
    blocked = client.post(
        f"/api/v1/companies/{company_id}/budgets",
        json={
            "name": "Поздно",
            "year": 2026,
            "basis": "cash",
            "lines": [{"month": 10, "metric_type": "cash_out", "amount": "1.00"}],
        },
        headers={"Idempotency-Key": "late-budget"},
    )
    assert blocked.status_code == 402


def test_alert_read_does_not_change_saved_signals(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "read-alert@example.com")
    wallet = _wallet(client, company_id, "100000.00")
    source = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Деньги",
            "type": "file",
            "namespace": "alert-cash",
            "format": "csv",
            "dataset": "cash",
        },
    )
    assert source.status_code == 200, source.text
    empty = client.get(f"/api/v1/companies/{company_id}/alerts")
    assert empty.status_code == 200, empty.text
    assert empty.json()["alerts"] == []
    assert empty.json()["report_date"] is None
    assert empty.json()["status"] == "unavailable"
    assert _count(admin, "alert_rules") == 0
    assert _count(admin, "alerts") == 0
    assert _count(admin, "forecast_runs") == 0
    again = client.get(f"/api/v1/companies/{company_id}/alerts?report_date=2099-01-01")
    assert again.status_code == 200, again.text
    assert again.json()["alerts"] == []
    assert _count(admin, "alert_rules") == 0
    assert _count(admin, "alerts") == 0
    assert _count(admin, "forecast_runs") == 0
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    due = today + timedelta(days=4)
    planned = client.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json={
            "direction": "out",
            "amount": "150000.00",
            "due_date": due.isoformat(),
            "expected_date": due.isoformat(),
            "wallet_id": wallet["id"],
        },
        headers={"Idempotency-Key": "alert-plan"},
    )
    assert planned.status_code == 200, planned.text
    first = _alerts(client, company_id)
    gap = [item for item in first["alerts"] if item["type"] == "cash_gap"]
    assert len(gap) == 1
    assert gap[0]["evidence"]["gap_date"] == due.isoformat()
    assert gap[0]["evidence"]["gap_amount"] == "50000.00"
    assert gap[0]["evidence"]["horizon_days"] == 7
    assert gap[0]["severity"] == "high"
    assert gap[0]["status"] == "open"
    assert gap[0]["calculated_on"] == today.isoformat()
    assert first["quality_flags"] == ["missing_source_coverage"]
    assert first["status"] == "preliminary"
    assert "_quality_flags" not in gap[0]["evidence"]
    second = _alerts(client, company_id)
    again_gap = next(item for item in second["alerts"] if item["type"] == "cash_gap")
    assert again_gap["id"] == gap[0]["id"]
    assert _count(admin, "alerts") == len(second["alerts"])
    saved = client.get(f"/api/v1/companies/{company_id}/alerts")
    listed = saved.json()
    assert listed["report_date"] == today.isoformat()
    assert listed["status"] == "preliminary"
    assert listed["completeness"] == "known"
    assert listed["quality_flags"] == ["missing_source_coverage"]
    listed_gap = next(item for item in listed["alerts"] if item["id"] == gap[0]["id"])
    assert listed_gap["status"] == "open"
    assert listed_gap["first_seen_at"] == gap[0]["first_seen_at"]
    repeat = client.get(f"/api/v1/companies/{company_id}/alerts")
    repeat_gap = next(item for item in repeat.json()["alerts"] if item["id"] == gap[0]["id"])
    assert repeat_gap["last_seen_at"] == listed_gap["last_seen_at"]
    assert repeat_gap["status"] == "open"
    assert _count(admin, "alerts") == len(second["alerts"])
    with admin.connect() as connection:
        acknowledged = connection.execute(
            text("SELECT count(*) FROM audit_log WHERE action = 'alert_acknowledged'")
        ).scalar_one()
    assert acknowledged == 0


def test_alert_preview_keeps_the_saved_signal(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "preview-alert@example.com")
    wallet = _wallet(client, company_id, "100000.00")
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    due = today + timedelta(days=4)
    later = today + timedelta(days=10)
    created = client.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json={
            "direction": "out",
            "amount": "150000.00",
            "due_date": due.isoformat(),
            "expected_date": due.isoformat(),
            "wallet_id": wallet["id"],
        },
        headers={"Idempotency-Key": "preview-plan"},
    )
    assert created.status_code == 200, created.text
    saved = _alerts(client, company_id)
    gap = next(item for item in saved["alerts"] if item["type"] == "cash_gap")
    rules_before = _count(admin, "alert_rules")
    runs_before = _count(admin, "forecast_runs")
    mail_before = _count(admin, "transactional_email_outbox")
    preview = client.get(
        f"/api/v1/companies/{company_id}/alerts/preview?report_date={later.isoformat()}"
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["persisted"] is False
    assert body["report_date"] == later.isoformat()
    shown = next(item for item in body["alerts"] if item["type"] == "cash_gap")
    assert shown["calculated_on"] == later.isoformat()
    assert "id" not in shown
    stored = client.get(f"/api/v1/companies/{company_id}/alerts")
    kept = next(item for item in stored.json()["alerts"] if item["id"] == gap["id"])
    assert kept["calculated_on"] == today.isoformat()
    assert kept["evidence"]["gap_date"] == due.isoformat()
    assert kept["evidence"]["gap_amount"] == "50000.00"
    assert kept["status"] == "open"
    assert kept["first_seen_at"] == gap["first_seen_at"]
    assert _count(admin, "alerts") == len(saved["alerts"])
    assert _count(admin, "alert_rules") == rules_before
    assert _count(admin, "forecast_runs") == runs_before
    assert _count(admin, "transactional_email_outbox") == mail_before
    assert _count(admin, "notification_outbox") == 0


def test_legacy_alert_without_completeness_is_not_final() -> None:
    from app.models.signals import Alert
    from app.services.alert_service import _saved_payload

    moment = datetime.now(ZoneInfo("Europe/Moscow"))
    company_id = uuid4()
    row = Alert(
        id=uuid4(),
        tenant_id=uuid4(),
        company_id=company_id,
        rule_type="cash_gap",
        fingerprint="cash_gap:legacy",
        severity="high",
        status="open",
        first_seen_at=moment,
        last_seen_at=moment,
        evidence_json={
            "as_of": "2026-10-16",
            "gap_date": "2026-10-20",
            "gap_amount": "29500.50",
        },
        source_refs=[],
        resolved_at=None,
    )
    payload = _saved_payload(type("Firm", (), {"id": company_id})(), [row])
    assert payload["status"] != "ready"
    assert payload["completeness"] == "unknown"
    assert payload["quality_flags"] == []
    assert payload["report_date"] == "2026-10-16"
    assert payload["alerts"][0]["status"] == "open"
    assert payload["alerts"][0]["evidence"]["gap_amount"] == "29500.50"


def test_alert_foreign_company_is_hidden(client, admin, app, fake, tmp_path) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, tmp_path, "owner-alert@example.com")
    foreign = TestClient(app)
    _ready(foreign, admin, app, fake, tmp_path, "foreign-alert@example.com")
    hidden = foreign.get(f"/api/v1/companies/{company_id}/alerts")
    assert hidden.status_code == 404
    denied = foreign.post(f"/api/v1/companies/{company_id}/alerts/recalculate")
    assert denied.status_code == 404
    preview = foreign.get(
        f"/api/v1/companies/{company_id}/alerts/preview?report_date=2026-10-16"
    )
    assert preview.status_code == 404
    assert _count(admin, "alerts") == 0


def _upload(client, company_id: str, connection_id: str, content: bytes, key: str):
    return client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": connection_id},
        files={"upload": ("budget.csv", content, "text/csv")},
        headers={"Idempotency-Key": key},
    )
