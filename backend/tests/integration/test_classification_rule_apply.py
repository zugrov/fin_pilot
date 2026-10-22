"""FA-R06.2-A2: детерминированное применение правил классификации."""

from __future__ import annotations

import threading
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
    set_rule_enabled,
)
from tests.synthetic_polygon.constants import PERIOD_QUERY, polygon_frozen_moment
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
    tenant_id = open_workspace(client, "Rule Apply")
    pay(client, app, fake, 1, "month")
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Rule Co", "kind": "company", "timezone": "Europe/Moscow"},
    )
    assert created.status_code == 200, created.text
    company_id = created.json()["id"]
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return company_id


def _source(client, company_id: str, wallet_id: str) -> str:
    created = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Bulk",
            "type": "file",
            "namespace": "bulk",
            "format": "csv",
            "encoding": "utf-8",
            "wallet_id": wallet_id,
        },
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _wallet_id(client, company_id: str) -> str:
    created = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Main", "type": "bank", "code": "main"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _user_id(client) -> str:
    profile = client.get("/api/v1/auth/me")
    assert profile.status_code == 200, profile.text
    return profile.json()["user"]["id"]


def _seed_bulk_posted(
    admin,
    *,
    tenant_id: str,
    company_id: str,
    wallet_id: str,
    user_id: str,
    count: int,
    description_prefix: str = "BulkTag",
) -> None:
    with admin.connect() as connection:
        for index in range(count):
            connection.execute(
                text(
                    """
                    INSERT INTO cash_transactions (
                        id, tenant_id, company_id, wallet_id, business_date, direction,
                        amount, currency, description, source, status,
                        classification_origin, locked_classification, created_by,
                        version, created_at, updated_at
                    )
                    VALUES (
                        gen_random_uuid(), CAST(:tid AS uuid), CAST(:cid AS uuid),
                        CAST(:wid AS uuid), DATE '2026-01-01' + (:offset * INTERVAL '1 day'),
                        'in', 1.00, 'RUB', :desc, 'manual', 'posted',
                        'none', FALSE, CAST(:uid AS uuid), 1, now(), now()
                    )
                    """
                ),
                {
                    "tid": tenant_id,
                    "cid": company_id,
                    "wid": wallet_id,
                    "uid": user_id,
                    "offset": index,
                    "desc": f"{description_prefix} {index}",
                },
            )
        connection.commit()


def _import_lines(client, company_id: str, connection_id: str, lines: str, key: str) -> None:
    uploaded = client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": connection_id},
        files={"upload": ("bulk.csv", (HEADER + lines).encode(), "application/octet-stream")},
        headers={"Idempotency-Key": key},
    )
    assert uploaded.status_code == 200, uploaded.text
    committed = client.post(f"/api/v1/imports/{uploaded.json()['id']}/commit")
    assert committed.status_code == 200, committed.text


def _bulk_rule() -> dict:
    return {
        "name": "Bulk in",
        "priority": 5,
        "conditions": {"direction": "in", "description_contains": "BulkTag"},
        "category_code": "operating",
    }


def _bulk_lines(count: int, *, day: str = "2026-01-01") -> str:
    rows = []
    for index in range(count):
        rows.append(
            f"b-{index},main,{day},in,1.00,RUB,,,BulkTag {index},,,\n"
        )
    return "".join(rows)


def test_apply_paginates_over_1000_transactions(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "bulk-1k@example.com")
    tenant_id = client.headers["X-Tenant-Id"]
    wallet_id = _wallet_id(client, company_id)
    _seed_bulk_posted(
        admin,
        tenant_id=tenant_id,
        company_id=company_id,
        wallet_id=wallet_id,
        user_id=_user_id(client),
        count=1001,
    )
    with admin.connect() as connection:
        seeded = connection.execute(
            text(
                "SELECT count(*) FROM cash_transactions WHERE company_id = CAST(:cid AS uuid)"
            ),
            {"cid": company_id},
        ).scalar_one()
    assert int(seeded) == 1001
    rule_id = create_rule(client, company_id, _bulk_rule())
    first = client.post(
        f"/api/v1/rules/{rule_id}/apply",
        json={"company_id": company_id},
    )
    assert first.status_code == 200, first.text
    body1 = first.json()
    assert body1["has_more"] is True
    assert body1["cursor"] is not None
    assert body1["applied"] == 1000
    second = client.post(
        f"/api/v1/rules/{rule_id}/apply",
        json={
            "company_id": company_id,
            "after_business_date": body1["cursor"]["business_date"],
            "after_transaction_id": body1["cursor"]["transaction_id"],
        },
    )
    assert second.status_code == 200, second.text
    body2 = second.json()
    assert body2["has_more"] is False
    assert body2["applied"] == 1
    totals = apply_rule_to_posted(client, company_id, rule_id)
    assert totals["applied"] == 0
    with admin.connect() as connection:
        tagged = connection.execute(
            text(
                """
                SELECT count(*) FROM cash_transactions
                WHERE company_id = CAST(:cid AS uuid)
                  AND classification_origin = 'rule'
                  AND description LIKE 'BulkTag%'
                """
            ),
            {"cid": company_id},
        ).scalar_one()
    assert int(tagged) == 1001


def test_preview_truncated_when_more_than_200_matches(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "prev-201@example.com")
    wallet_id = _wallet_id(client, company_id)
    source_id = _source(client, company_id, wallet_id)
    _import_lines(client, company_id, source_id, _bulk_lines(201), "prev-201")
    rule_id = create_rule(client, company_id, _bulk_rule())
    preview = client.post(
        f"/api/v1/rules/{rule_id}/preview",
        json={"company_id": company_id},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["total_matches"] == 201
    assert body["truncated"] is True
    assert len(body["matches"]) == 200


def test_apply_skips_when_higher_priority_rule_wins(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "prio-apply@example.com")
    wallet_id = _wallet_id(client, company_id)
    source_id = _source(client, company_id, wallet_id)
    _import_lines(
        client,
        company_id,
        source_id,
        "prio-1,main,2026-02-01,in,7200.00,RUB,7700000202,,Оплата retail,,,\n",
        "prio-one",
    )
    high_id = create_rule(
        client,
        company_id,
        {
            "name": "Winning",
            "priority": 1,
            "conditions": {"direction": "in", "counterparty_inn": "7700000202"},
            "category_code": "investing",
        },
    )
    low_id = create_rule(
        client,
        company_id,
        {**RETAIL_CLIENTBANK_IN_RULE, "priority": 50},
    )
    assert client.post(
        f"/api/v1/rules/{high_id}/apply",
        json={"company_id": company_id},
    ).json()["applied"] == 1
    applied = client.post(
        f"/api/v1/rules/{low_id}/apply",
        json={"company_id": company_id},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] == 0
    assert applied.json()["skipped_higher_priority"] == 1
    with admin.connect() as connection:
        code = connection.execute(
            text(
                """
                SELECT cc.code FROM cash_transactions ct
                JOIN cash_categories cc ON cc.id = ct.category_id
                WHERE ct.company_id = CAST(:cid AS uuid)
                """
            ),
            {"cid": company_id},
        ).scalar_one()
    assert code == "investing"
    assert high_id != low_id


def test_viewer_cannot_apply(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "viewer-apply@example.com")
    tenant = client.headers["X-Tenant-Id"]
    rule_id = create_rule(client, company_id, _bulk_rule())
    invited = client.post(
        f"/api/v1/workspaces/{tenant}/invitations",
        json={"email": "viewer-apply-guest@example.com", "role": "viewer"},
    )
    assert invited.status_code == 200, invited.text
    invite_token = token_from_link(latest_link(admin))
    guest = TestClient(app)
    register_and_verify(guest, admin, "viewer-apply-guest@example.com")
    guest_login = login(guest, "viewer-apply-guest@example.com")
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
    blocked = guest.post(
        f"/api/v1/rules/{rule_id}/apply",
        json={"company_id": company_id},
    )
    assert blocked.status_code == 403


def test_unpaid_apply_returns_402(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "unpaid-apply@example.com")
    rule_id = create_rule(client, company_id, _bulk_rule())
    end = client.get("/api/v1/billing/subscription").json()["paid_through"]
    freeze(app, datetime.fromisoformat(end) + timedelta(seconds=1))
    login(client, "unpaid-apply@example.com")
    memberships = client.get("/api/v1/auth/me").json()["memberships"]
    client.headers["X-Tenant-Id"] = memberships[0]["tenant_id"]
    blocked = client.post(
        f"/api/v1/rules/{rule_id}/apply",
        json={"company_id": company_id},
    )
    assert blocked.status_code == 402


def test_foreign_company_rule_returns_404(client, admin, app, fake, tmp_path) -> None:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, "two-rule-co@example.com")
    login(client, "two-rule-co@example.com")
    tenant_id = open_workspace(client, "Two")
    pay(client, app, fake, 2, "month")
    first = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "A", "kind": "company"},
    )
    second = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "B", "kind": "company"},
    )
    company_a = first.json()["id"]
    company_b = second.json()["id"]
    for cid in (company_a, company_b):
        assert client.post(f"/api/v1/billing/companies/{cid}/activate").status_code == 200
    rule_id = create_rule(client, company_b, _bulk_rule())
    missing = client.post(
        f"/api/v1/rules/{rule_id}/apply",
        json={"company_id": company_a},
    )
    assert missing.status_code == 404


def test_disabled_rule_apply_returns_409(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "disabled-apply@example.com")
    rule_id = create_rule(client, company_id, _bulk_rule())
    set_rule_enabled(admin, rule_id, False)
    blocked = client.post(
        f"/api/v1/rules/{rule_id}/apply",
        json={"company_id": company_id},
    )
    assert blocked.status_code == 409


def test_apply_audit_once_per_call(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "audit-apply@example.com")
    wallet_id = _wallet_id(client, company_id)
    source_id = _source(client, company_id, wallet_id)
    _import_lines(client, company_id, source_id, _bulk_lines(3), "audit-3")
    rule_id = create_rule(client, company_id, _bulk_rule())
    response = client.post(
        f"/api/v1/rules/{rule_id}/apply",
        json={"company_id": company_id},
    )
    assert response.status_code == 200, response.text
    with admin.connect() as connection:
        count = connection.execute(
            text(
                """
                SELECT count(*) FROM audit_log
                WHERE action = 'rule_applied'
                  AND entity_id = CAST(:rid AS uuid)
                """
            ),
            {"rid": rule_id},
        ).scalar_one()
        row = connection.execute(
            text(
                """
                SELECT after_redacted FROM audit_log
                WHERE action = 'rule_applied'
                  AND entity_id = CAST(:rid AS uuid)
                LIMIT 1
                """
            ),
            {"rid": rule_id},
        ).scalar_one()
    assert int(count) == 1
    assert "applied" in row
    assert "transaction_id" not in str(row)


def test_apply_respects_locked_and_existing_category(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "skip-cat@example.com")
    load_retail_polygon(client, company_id, admin=admin)
    listed = client.get(f"/api/v1/companies/{company_id}/transactions?limit=50")
    cb_tx = next(item for item in listed.json()["transactions"] if item["amount"] == "7200.00")
    with admin.connect() as connection:
        category = connection.execute(
            text("SELECT id FROM cash_categories WHERE code = 'investing' LIMIT 1")
        ).scalar_one()
    assert client.post(
        f"/api/v1/transactions/{cb_tx['id']}/classify",
        json={"version": cb_tx["version"], "category_id": str(category)},
    ).status_code == 200
    rule_id = create_rule(client, company_id, RETAIL_CLIENTBANK_IN_RULE)
    body = apply_rule_to_posted(client, company_id, rule_id)
    assert body["applied"] == 0
    assert body["skipped_locked"] >= 1


def test_polygon_cashflow_unchanged_group_oracle(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    group_before = group_totals_oracle()
    company_id = _company(client, admin, app, fake, tmp_path, "poly-oracle@example.com")
    load_retail_polygon(client, company_id, admin=admin)
    before = client.get(f"/api/v1/companies/{company_id}/cashflow?{PERIOD_QUERY}")
    assert before.status_code == 200, before.text
    assert section_amounts(before.json())["unmapped"] == ("7200.00", "0.00")
    rule_id = create_rule(client, company_id, RETAIL_CLIENTBANK_IN_RULE)
    apply_rule_to_posted(client, company_id, rule_id)
    after = client.get(f"/api/v1/companies/{company_id}/cashflow?{PERIOD_QUERY}")
    assert after.status_code == 200, after.text
    assert section_amounts(after.json())["operating"] == ("22200.00", "2500.00")
    assert section_amounts(after.json())["unmapped"] == ("0.00", "0.00")
    second_apply = apply_rule_to_posted(client, company_id, rule_id)
    assert second_apply["applied"] == 0
    stable = client.get(f"/api/v1/companies/{company_id}/cashflow?{PERIOD_QUERY}")
    assert section_amounts(stable.json()) == section_amounts(after.json())
    assert group_totals_oracle() == group_before


def test_apply_does_not_overwrite_manual_classification_race(
    client, admin, app, fake, tmp_path
) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "race-manual@example.com")
    wallet_id = _wallet_id(client, company_id)
    source_id = _source(client, company_id, wallet_id)
    _import_lines(
        client,
        company_id,
        source_id,
        "race-1,main,2026-03-01,in,10.00,RUB,,,BulkTag race,,,\n"
        + _bulk_lines(50, day="2026-03-02"),
        "race-one",
    )
    rule_id = create_rule(client, company_id, _bulk_rule())
    listed = client.get(f"/api/v1/companies/{company_id}/transactions?limit=200")
    txs = listed.json()["transactions"]
    tx = next(item for item in txs if item["description"] == "BulkTag race")
    with admin.connect() as connection:
        category = connection.execute(
            text("SELECT id FROM cash_categories WHERE code = 'investing' LIMIT 1")
        ).scalar_one()
    email = "race-manual@example.com"
    tenant = client.headers["X-Tenant-Id"]
    row_locked = threading.Event()
    release = threading.Event()

    def hold_row() -> None:
        with admin.connect() as connection:
            connection.execute(text("BEGIN"))
            connection.execute(
                text(
                    "SELECT id FROM cash_transactions WHERE id = CAST(:id AS uuid) FOR UPDATE"
                ),
                {"id": tx["id"]},
            )
            row_locked.set()
            assert release.wait(15)
            connection.execute(text("COMMIT"))

    def run_apply() -> None:
        worker = TestClient(app)
        login(worker, email)
        worker.headers["X-Tenant-Id"] = tenant
        row_locked.wait(15)
        worker.post(
            f"/api/v1/rules/{rule_id}/apply",
            json={"company_id": company_id},
        )

    classify = TestClient(app)
    login(classify, email)
    classify.headers["X-Tenant-Id"] = tenant

    def run_classify() -> None:
        row_locked.wait(15)
        classify.post(
            f"/api/v1/transactions/{tx['id']}/classify",
            json={"version": tx["version"], "category_id": str(category)},
        )

    holder = threading.Thread(target=hold_row)
    holder.start()
    row_locked.wait(15)
    classify_thread = threading.Thread(target=run_classify)
    apply_thread = threading.Thread(target=run_apply)
    classify_thread.start()
    apply_thread.start()
    release.set()
    classify_thread.join(timeout=30)
    apply_thread.join(timeout=30)
    holder.join(timeout=30)
    with admin.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT locked_classification, classification_origin,
                       category_id::text
                FROM cash_transactions WHERE id = CAST(:id AS uuid)
                """
            ),
            {"id": tx["id"]},
        ).one()
    assert row.locked_classification is True
    assert row.classification_origin == "manual"
    assert row.category_id == str(category)
