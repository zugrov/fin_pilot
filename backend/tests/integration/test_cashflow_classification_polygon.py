"""FA-R06.2-A: ClassificationRule на полигоне retail / ClientBank."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import freeze, login, open_workspace, pay, register_and_verify
from tests.synthetic_polygon.cashflow_oracle import section_amounts
from tests.synthetic_polygon.classification_harness import (
    RETAIL_CLIENTBANK_IN_RULE,
    apply_rule_to_posted,
    create_rule,
    load_retail_polygon,
    set_rule_enabled,
)
from tests.synthetic_polygon.constants import PERIOD_QUERY, polygon_frozen_moment


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
    tenant_id = open_workspace(client, "Classify Polygon")
    pay(client, app, fake, 1, "month")
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Retail Rule Co", "kind": "company", "timezone": "Europe/Moscow"},
    )
    assert created.status_code == 200, created.text
    company_id = created.json()["id"]
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return company_id


def _cashflow(client, company_id: str) -> dict:
    response = client.get(f"/api/v1/companies/{company_id}/cashflow?{PERIOD_QUERY}")
    assert response.status_code == 200, response.text
    return response.json()


def _assert_retail_classified_operating(body: dict) -> None:
    amounts = section_amounts(body)
    assert amounts["operating"] == ("22200.00", "2500.00")
    assert amounts["unmapped"] == ("0.00", "0.00")
    assert body["net_external"] == "19700.00"


def test_rule_before_import_classifies_clientbank(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "rule-before@example.com")
    create_rule(client, company_id, RETAIL_CLIENTBANK_IN_RULE)
    load_retail_polygon(client, company_id, admin=admin)
    _assert_retail_classified_operating(_cashflow(client, company_id))


def test_rule_after_import_via_preview_apply(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "rule-after@example.com")
    load_retail_polygon(client, company_id, admin=admin)
    before = _cashflow(client, company_id)
    assert section_amounts(before)["unmapped"] == ("7200.00", "0.00")
    rule_id = create_rule(client, company_id, RETAIL_CLIENTBANK_IN_RULE)
    preview = client.post(
        f"/api/v1/rules/{rule_id}/preview",
        json={"company_id": company_id},
    )
    assert preview.status_code == 200, preview.text
    assert len(preview.json()["matches"]) == 1
    applied = apply_rule_to_posted(client, company_id, rule_id)
    assert applied["applied"] == 1
    _assert_retail_classified_operating(_cashflow(client, company_id))


def test_rule_priority_lower_number_wins(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "rule-prio@example.com")
    create_rule(
        client,
        company_id,
        {
            **RETAIL_CLIENTBANK_IN_RULE,
            "name": "Investing first",
            "priority": 1,
            "category_code": "investing",
        },
    )
    create_rule(client, company_id, {**RETAIL_CLIENTBANK_IN_RULE, "priority": 50})
    load_retail_polygon(client, company_id, admin=admin)
    amounts = section_amounts(_cashflow(client, company_id))
    assert amounts["investing"] == ("7200.00", "0.00")
    assert amounts["operating"] == ("15000.00", "2500.00")
    assert amounts["unmapped"] == ("0.00", "0.00")


def test_disabled_rule_not_applied_on_import(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "rule-off@example.com")
    rule_id = create_rule(client, company_id, RETAIL_CLIENTBANK_IN_RULE)
    set_rule_enabled(admin, rule_id, False)
    load_retail_polygon(client, company_id, admin=admin)
    assert section_amounts(_cashflow(client, company_id))["unmapped"] == ("7200.00", "0.00")


def test_rule_other_company_not_applied(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, "two-co@example.com")
    login(client, "two-co@example.com")
    tenant_id = open_workspace(client, "Two Cos")
    pay(client, app, fake, 2, "month")
    first = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Retail A", "kind": "company", "timezone": "Europe/Moscow"},
    )
    second = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Retail B", "kind": "company", "timezone": "Europe/Moscow"},
    )
    assert first.status_code == 200 and second.status_code == 200
    company_a = first.json()["id"]
    company_b = second.json()["id"]
    for cid in (company_a, company_b):
        assert client.post(f"/api/v1/billing/companies/{cid}/activate").status_code == 200
    create_rule(client, company_b, RETAIL_CLIENTBANK_IN_RULE)
    load_retail_polygon(client, company_a, admin=admin)
    assert section_amounts(_cashflow(client, company_a))["unmapped"] == ("7200.00", "0.00")


def test_rule_other_tenant_not_applied(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "tenant-a@example.com")
    with admin.connect() as connection:
        connection.execute(
            text(
                """
                INSERT INTO classification_rules (
                    id, tenant_id, company_id, name, priority,
                    conditions_json, actions_json, enabled, version, created_at
                )
                VALUES (
                    gen_random_uuid(), CAST(:other AS uuid), NULL,
                    'Foreign tenant rule', 1,
                    CAST(:conditions AS jsonb),
                    CAST(:actions AS jsonb),
                    TRUE, 1, now()
                )
                """
            ),
            {
                "other": str(uuid4()),
                "conditions": '{"direction": "in", "counterparty_inn": "7700000202"}',
                "actions": '{"category_code": "operating"}',
            },
        )
        connection.commit()
    load_retail_polygon(client, company_id, admin=admin)
    assert section_amounts(_cashflow(client, company_id))["unmapped"] == ("7200.00", "0.00")


def test_explicit_csv_category_not_overwritten_by_rule(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "csv-cat@example.com")
    create_rule(
        client,
        company_id,
        {
            "name": "Catch retail csv in",
            "priority": 1,
            "conditions": {"description_contains": "Розничная", "direction": "in"},
            "category_code": "investing",
        },
    )
    load_retail_polygon(client, company_id, admin=admin)
    amounts = section_amounts(_cashflow(client, company_id))
    assert amounts["operating"] == ("15000.00", "2500.00")
    assert amounts["investing"] == ("0.00", "0.00")
    assert amounts["unmapped"] == ("7200.00", "0.00")


def test_preview_apply_skips_locked_category(client, admin, app, fake, tmp_path) -> None:
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "apply-skip@example.com")
    load_retail_polygon(client, company_id, admin=admin)
    listed = client.get(f"/api/v1/companies/{company_id}/transactions?limit=50")
    assert listed.status_code == 200, listed.text
    cb_tx = next(
        item for item in listed.json()["transactions"] if item["amount"] == "7200.00"
    )
    with admin.connect() as connection:
        category = connection.execute(
            text("SELECT id FROM cash_categories WHERE code = 'investing' LIMIT 1")
        ).scalar_one()
    locked = client.post(
        f"/api/v1/transactions/{cb_tx['id']}/classify",
        json={"version": cb_tx["version"], "category_id": str(category)},
    )
    assert locked.status_code == 200, locked.text
    rule_id = create_rule(client, company_id, RETAIL_CLIENTBANK_IN_RULE)
    body = apply_rule_to_posted(client, company_id, rule_id)
    assert body["applied"] == 0
    assert body["skipped_locked"] >= 1
