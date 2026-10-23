import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import login, open_workspace, pay, register_and_verify
from tests.synthetic_polygon.classification_harness import create_rule


@pytest.fixture(autouse=True)
def _guard_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


def test_foreign_tenant_rule_cannot_link_evidence(client, admin, app, fake, tmp_path) -> None:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, "rls-a@example.com")
    login(client, "rls-a@example.com")
    tenant_a = open_workspace(client, "A")
    pay(client, app, fake, 1, "month")
    company_a = client.post(
        f"/api/v1/workspaces/{tenant_a}/companies",
        json={"name": "A", "kind": "company"},
    ).json()["id"]
    client.post(f"/api/v1/billing/companies/{company_a}/activate")
    wallet_a = client.post(
        f"/api/v1/companies/{company_a}/wallets",
        json={"name": "W", "type": "bank"},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    ).json()["id"]

    register_and_verify(client, admin, "rls-b@example.com")
    login(client, "rls-b@example.com")
    tenant_b = open_workspace(client, "B")
    pay(client, app, fake, 1, "month")
    company_b = client.post(
        f"/api/v1/workspaces/{tenant_b}/companies",
        json={"name": "B", "kind": "company"},
    ).json()["id"]
    client.post(f"/api/v1/billing/companies/{company_b}/activate")
    rule_b = create_rule(
        client,
        company_b,
        {
            "name": "B rule",
            "priority": 1,
            "conditions": {"direction": "in"},
            "category_code": "operating",
        },
    )

    tx_a = uuid.uuid4()
    user_a = uuid.uuid4()
    with admin.connect() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, email, normalized_email, password_hash, name, created_at) "
                "VALUES (:id, 'u@example.com', 'u@example.com', 'x', 'u', now())"
            ),
            {"id": user_a},
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO cash_transactions "
                    "(id, tenant_id, company_id, wallet_id, business_date, direction, amount, "
                    "currency, description, source, status, classification_origin, "
                    "locked_classification, created_by, version, created_at, updated_at, "
                    "classification_rule_id, classification_rule_version) "
                    "VALUES (:id, :t, :c, :w, '2026-01-01', 'in', 1.00, 'RUB', 'x', 'manual', "
                    "'posted', 'rule', false, :u, 1, now(), now(), CAST(:rid AS uuid), 1)"
                ),
                {
                    "id": tx_a,
                    "t": uuid.UUID(tenant_a),
                    "c": uuid.UUID(company_a),
                    "w": uuid.UUID(wallet_a),
                    "u": user_a,
                    "rid": rule_b,
                },
            )
        connection.commit()
