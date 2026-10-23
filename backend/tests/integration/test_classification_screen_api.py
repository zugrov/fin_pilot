"""FA-R06.2-B0: PATCH правил и API неклассифицированных операций."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import (
    freeze,
    latest_link,
    login,
    open_workspace,
    pay,
    register_and_verify,
    token_from_link,
)
from tests.synthetic_polygon.cashflow_oracle import section_amounts
from tests.synthetic_polygon.classification_harness import (
    RETAIL_CLIENTBANK_IN_RULE,
    apply_rule_to_posted,
    create_rule,
    load_retail_polygon,
)
from tests.synthetic_polygon.constants import (
    PERIOD_FROM,
    PERIOD_QUERY,
    PERIOD_TO,
    polygon_frozen_moment,
)
from tests.synthetic_polygon.digest_expectations import group_totals_oracle

HEADER = (
    "external_id,wallet_code,business_date,direction,amount,currency,"
    "counterparty_inn,counterparty_name,description,document_number,category_code,direction_code\n"
)


@pytest.fixture(autouse=True)
def _guard_test_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


@pytest.fixture(autouse=True)
def _balances_import_enabled(app):
    app.state.settings.balances_import_enabled = True


def _company(client, admin, app, fake, tmp_path, email: str) -> str:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Classify Screen")
    pay(client, app, fake, 1, "month")
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Screen Co", "kind": "company", "timezone": "Europe/Moscow"},
    )
    assert created.status_code == 200, created.text
    company_id = created.json()["id"]
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return company_id


def _wallet(client, company_id: str) -> str:
    created = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Main", "type": "bank", "code": "main"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _source(client, company_id: str, wallet_id: str, namespace: str) -> str:
    created = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": f"src-{namespace}",
            "type": "file",
            "namespace": namespace,
            "format": "csv",
            "encoding": "utf-8",
            "wallet_id": wallet_id,
        },
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _import_csv(client, company_id: str, source_id: str, body: str, key: str) -> None:
    uploaded = client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": source_id},
        files={"upload": ("rows.csv", (HEADER + body).encode(), "application/octet-stream")},
        headers={"Idempotency-Key": key},
    )
    assert uploaded.status_code == 200, uploaded.text
    committed = client.post(f"/api/v1/imports/{uploaded.json()['id']}/commit")
    assert committed.status_code == 200, committed.text


def _summary(client, company_id: str) -> dict:
    response = client.get(
        f"/api/v1/companies/{company_id}/transactions/unclassified/summary"
        f"?date_from={PERIOD_FROM}&date_to={PERIOD_TO}"
    )
    assert response.status_code == 200, response.text
    return response.json()


def _patch_rule(client, company_id: str, rule_id: str, **fields) -> dict:
    response = client.patch(
        f"/api/v1/rules/{rule_id}",
        json={"company_id": company_id, **fields},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_create_rule_rejects_empty_conditions(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "empty-cond@example.com")
    response = client.post(
        f"/api/v1/companies/{company_id}/classification-rules",
        json={
            "name": "Пустое",
            "priority": 10,
            "conditions": {},
            "category_code": "operating",
        },
        headers={"Idempotency-Key": "empty-cond-key"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["message"] == "Нужно хотя бы одно условие"


def test_create_rule_idempotent(client, admin, app, fake, tmp_path) -> None:
    from uuid import uuid4

    company_id = _company(client, admin, app, fake, tmp_path, "idem-rule@example.com")
    body = {
        "name": "Idem",
        "priority": 5,
        "conditions": {"direction": "in"},
        "category_code": "operating",
    }
    key = str(uuid4())
    first = client.post(
        f"/api/v1/companies/{company_id}/classification-rules",
        json=body,
        headers={"Idempotency-Key": key},
    )
    second = client.post(
        f"/api/v1/companies/{company_id}/classification-rules",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]
    listed = client.get(f"/api/v1/companies/{company_id}/classification-rules")
    assert len(listed.json()["rules"]) == 1


def test_create_rule_replay_returns_same_warning(client, admin, app, fake, tmp_path) -> None:
    from uuid import uuid4

    company_id = _company(client, admin, app, fake, tmp_path, "warn-replay@example.com")
    client.post(
        f"/api/v1/companies/{company_id}/classification-rules",
        json={
            "name": "First conflict",
            "priority": 7,
            "conditions": {"direction": "in"},
            "category_code": "operating",
        },
        headers={"Idempotency-Key": str(uuid4())},
    )
    body = {
        "name": "Second conflict",
        "priority": 7,
        "conditions": {"direction": "out"},
        "category_code": "investing",
    }
    key = str(uuid4())
    first = client.post(
        f"/api/v1/companies/{company_id}/classification-rules",
        json=body,
        headers={"Idempotency-Key": key},
    )
    second = client.post(
        f"/api/v1/companies/{company_id}/classification-rules",
        json=body,
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json().get("warnings") == second.json().get("warnings")
    assert first.json().get("warnings")


def test_create_rule_requires_idempotency_key(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "no-key@example.com")
    response = client.post(
        f"/api/v1/companies/{company_id}/classification-rules",
        json={
            "name": "Без ключа",
            "priority": 10,
            "conditions": {"direction": "in"},
            "category_code": "operating",
        },
    )
    assert response.status_code == 400, response.text
    assert response.json()["message"] == "Нужен Idempotency-Key"


def test_create_rule_idempotency_conflict(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "idem-conflict@example.com")
    key = str(uuid4())
    first_body = {
        "name": "Первое",
        "priority": 10,
        "conditions": {"direction": "in"},
        "category_code": "operating",
    }
    second_body = {**first_body, "name": "Другое имя"}
    ok = client.post(
        f"/api/v1/companies/{company_id}/classification-rules",
        json=first_body,
        headers={"Idempotency-Key": key},
    )
    assert ok.status_code == 200, ok.text
    clash = client.post(
        f"/api/v1/companies/{company_id}/classification-rules",
        json=second_body,
        headers={"Idempotency-Key": key},
    )
    assert clash.status_code == 409, clash.text
    assert clash.json()["code"] == "idempotency_conflict"


def test_create_rule_two_keys_same_body_creates_two_rules(
    client, admin, app, fake, tmp_path
) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "two-keys@example.com")
    body = {
        "name": "Дубликат тела",
        "priority": 10,
        "conditions": {"direction": "out"},
        "category_code": "operating",
    }
    first = client.post(
        f"/api/v1/companies/{company_id}/classification-rules",
        json=body,
        headers={"Idempotency-Key": str(uuid4())},
    )
    second = client.post(
        f"/api/v1/companies/{company_id}/classification-rules",
        json=body,
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] != second.json()["id"]
    listed = client.get(f"/api/v1/companies/{company_id}/classification-rules")
    assert len(listed.json()["rules"]) == 2


def test_patch_rule_guards_and_audit(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "patch-guards@example.com")
    rule_id = create_rule(client, company_id, RETAIL_CLIENTBANK_IN_RULE)
    tenant = client.headers["X-Tenant-Id"]
    invited = client.post(
        f"/api/v1/workspaces/{tenant}/invitations",
        json={"email": "patch-viewer@example.com", "role": "viewer"},
    )
    assert invited.status_code == 200, invited.text
    invite_token = token_from_link(latest_link(admin))
    guest = TestClient(app)
    register_and_verify(guest, admin, "patch-viewer@example.com")
    guest_login = login(guest, "patch-viewer@example.com")
    accepted = guest.post(
        "/api/v1/auth/invitations/accept",
        json={"token": invite_token},
    )
    assert accepted.status_code == 200
    guest.headers["X-Tenant-Id"] = tenant
    grant = client.post(
        f"/api/v1/workspaces/{tenant}/company-access",
        json={"user_id": guest_login["user"]["id"], "company_id": company_id},
    )
    assert grant.status_code == 200, grant.text
    denied = guest.patch(
        f"/api/v1/rules/{rule_id}",
        json={"company_id": company_id, "enabled": False},
    )
    assert denied.status_code == 403
    end = client.get("/api/v1/billing/subscription").json()["paid_through"]
    freeze(app, datetime.fromisoformat(end) + timedelta(seconds=1))
    login(client, "patch-guards@example.com")
    client.headers["X-Tenant-Id"] = tenant
    blocked = client.patch(
        f"/api/v1/rules/{rule_id}",
        json={"company_id": company_id, "enabled": False},
    )
    assert blocked.status_code == 402
    freeze(app, polygon_frozen_moment())
    login(client, "patch-guards@example.com")
    client.headers["X-Tenant-Id"] = tenant
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, "other-co@example.com")
    login(client, "other-co@example.com")
    other_tenant = open_workspace(client, "Other")
    pay(client, app, fake, 1, "month")
    other = client.post(
        f"/api/v1/workspaces/{other_tenant}/companies",
        json={"name": "Other", "kind": "company"},
    )
    other_id = other.json()["id"]
    assert client.post(f"/api/v1/billing/companies/{other_id}/activate").status_code == 200
    missing = client.patch(
        f"/api/v1/rules/{rule_id}",
        json={"company_id": other_id, "enabled": False},
    )
    assert missing.status_code == 404
    login(client, "patch-guards@example.com")
    client.headers["X-Tenant-Id"] = tenant
    updated = _patch_rule(client, company_id, rule_id, name="Renamed rule", priority=20)
    assert updated["name"] == "Renamed rule"
    assert updated["priority"] == 20
    assert updated["version"] == 2
    with admin.connect() as connection:
        audits = connection.execute(
            text(
                """
                SELECT count(*) FROM audit_log
                WHERE action = 'rule_updated' AND entity_id = CAST(:rid AS uuid)
                """
            ),
            {"rid": rule_id},
        ).scalar_one()
        payload = connection.execute(
            text(
                """
                SELECT after_redacted::text FROM audit_log
                WHERE action = 'rule_updated' AND entity_id = CAST(:rid AS uuid)
                LIMIT 1
                """
            ),
            {"rid": rule_id},
        ).scalar_one()
    assert int(audits) == 1
    assert "conditions" not in payload
    again = _patch_rule(client, company_id, rule_id, name="Renamed rule")
    assert again["version"] == 2


def test_disabled_rule_stops_apply_and_import(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "patch-off@example.com")
    rule_id = create_rule(client, company_id, RETAIL_CLIENTBANK_IN_RULE)
    _patch_rule(client, company_id, rule_id, enabled=False)
    blocked = client.post(
        f"/api/v1/rules/{rule_id}/apply",
        json={"company_id": company_id},
    )
    assert blocked.status_code == 409
    load_retail_polygon(client, company_id, admin=admin)
    assert _summary(client, company_id)["in"] == {"count": 1, "amount": "7200.00"}


def test_patch_priority_changes_import_winner(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "patch-prio@example.com")
    low_id = create_rule(
        client,
        company_id,
        {
            **RETAIL_CLIENTBANK_IN_RULE,
            "name": "Operating later",
            "priority": 50,
        },
    )
    high_id = create_rule(
        client,
        company_id,
        {
            "name": "Investing first",
            "priority": 1,
            "conditions": RETAIL_CLIENTBANK_IN_RULE["conditions"],
            "category_code": "investing",
        },
    )
    _patch_rule(client, company_id, high_id, priority=100)
    load_retail_polygon(client, company_id, admin=admin)
    with admin.connect() as connection:
        code = connection.execute(
            text(
                """
                SELECT cc.code FROM cash_transactions ct
                JOIN cash_categories cc ON cc.id = ct.category_id
                WHERE ct.company_id = CAST(:cid AS uuid) AND ct.amount = 7200.00
                """
            ),
            {"cid": company_id},
        ).scalar_one()
    assert code == "operating"
    assert low_id != high_id


def test_unclassified_retail_oracle_and_pagination(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    group_before = group_totals_oracle()
    company_id = _company(client, admin, app, fake, tmp_path, "uncls-retail@example.com")
    load_retail_polygon(client, company_id, admin=admin)
    before_cf = client.get(f"/api/v1/companies/{company_id}/cashflow?{PERIOD_QUERY}")
    assert before_cf.status_code == 200, before_cf.text
    summary_before = _summary(client, company_id)
    assert summary_before["in"] == {"count": 1, "amount": "7200.00"}
    assert summary_before["out"] == {"count": 0, "amount": "0.00"}
    listed = client.get(
        f"/api/v1/companies/{company_id}/transactions/unclassified"
        f"?date_from={PERIOD_FROM}&date_to={PERIOD_TO}&limit=10"
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert len(body["transactions"]) == 1
    assert body["transactions"][0]["amount"] == "7200.00"
    assert body["has_more"] is False
    categories = client.get(f"/api/v1/companies/{company_id}/cash-categories")
    assert categories.status_code == 200, categories.text
    assert any(item["code"] == "operating" for item in categories.json()["categories"])
    rule_id = create_rule(client, company_id, RETAIL_CLIENTBANK_IN_RULE)
    apply_rule_to_posted(client, company_id, rule_id)
    summary_after = _summary(client, company_id)
    assert summary_after["in"] == {"count": 0, "amount": "0.00"}
    empty = client.get(
        f"/api/v1/companies/{company_id}/transactions/unclassified"
        f"?date_from={PERIOD_FROM}&date_to={PERIOD_TO}"
    )
    assert empty.json()["transactions"] == []
    after_cf = client.get(f"/api/v1/companies/{company_id}/cashflow?{PERIOD_QUERY}")
    assert section_amounts(after_cf.json())["operating"] == ("22200.00", "2500.00")
    assert section_amounts(after_cf.json())["unmapped"] == ("0.00", "0.00")
    assert group_totals_oracle() == group_before


def test_unclassified_cursor_pagination(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "uncls-page@example.com")
    wallet_id = _wallet(client, company_id)
    source_id = _source(client, company_id, wallet_id, "page")
    lines = "".join(
        f"p-{index},main,2026-05-01,in,1.00,RUB,,,BulkTag {index},,,\n" for index in range(15)
    )
    _import_csv(client, company_id, source_id, lines, "page-15")
    first = client.get(
        f"/api/v1/companies/{company_id}/transactions/unclassified?limit=10"
    )
    assert first.status_code == 200, first.text
    page1 = first.json()
    assert len(page1["transactions"]) == 10
    assert page1["has_more"] is True
    assert page1["cursor"] is not None
    second = client.get(
        f"/api/v1/companies/{company_id}/transactions/unclassified"
        f"?limit=10&after_business_date={page1['cursor']['business_date']}"
        f"&after_transaction_id={page1['cursor']['transaction_id']}"
    )
    assert second.status_code == 200, second.text
    page2 = second.json()
    assert len(page2["transactions"]) == 5
    assert page2["has_more"] is False
