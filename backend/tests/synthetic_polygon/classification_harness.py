"""Правила классификации ClientBank retail (FA-R06.2-A)."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from tests.synthetic_polygon.harness import load_profile
from tests.synthetic_polygon.profiles import RETAIL

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_polygon" / "retail"
CLIENTBANK = FIXTURES / "clientbank.txt"

# Условия только из CONDITION_KEYS import_service.
RETAIL_CLIENTBANK_IN_RULE = {
    "name": "Retail ClientBank operating in",
    "priority": 10,
    "conditions": {
        "direction": "in",
        "counterparty_inn": "7700000202",
        "description_contains": "Оплата",
    },
    "category_code": "operating",
}


def create_rule(client: TestClient, company_id: str, rule: dict) -> str:
    created = client.post(
        f"/api/v1/companies/{company_id}/classification-rules",
        json=rule,
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def load_retail_polygon(
    client: TestClient, company_id: str, *, admin: Engine | None = None
) -> None:
    load_profile(client, company_id, RETAIL, admin=admin)


def apply_rule_to_posted(client: TestClient, company_id: str, rule_id: str) -> dict:
    """POST /rules/{id}/preview с apply=true — retroactive rule application."""
    response = client.post(
        f"/api/v1/rules/{rule_id}/preview",
        json={"company_id": company_id, "apply": True},
    )
    assert response.status_code == 200, response.text
    return response.json()


def recommit_clientbank(
    client: TestClient, company_id: str, wallet_id: str, namespace: str
) -> None:
    source = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": f"cb-{namespace}",
            "type": "clientbank",
            "namespace": namespace,
            "format": "clientbank",
            "dataset": "cash",
            "wallet_id": wallet_id,
        },
    )
    assert source.status_code == 200, source.text
    uploaded = client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": source.json()["id"]},
        files={"upload": ("clientbank.txt", CLIENTBANK.read_bytes(), "application/octet-stream")},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert uploaded.status_code == 200, uploaded.text
    committed = client.post(f"/api/v1/imports/{uploaded.json()['id']}/commit")
    assert committed.status_code == 200, committed.text


def set_rule_enabled(admin: Engine, rule_id: str, enabled: bool) -> None:
    with admin.connect() as connection:
        connection.execute(
            text(
                "UPDATE classification_rules SET enabled = :en "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"en": enabled, "id": rule_id},
        )
        connection.commit()


def insert_tenant_wide_rule(admin: Engine, tenant_id: str, rule: dict) -> str:
    """Правило tenant scope (company_id NULL) — только для негативных тестов."""
    with admin.connect() as connection:
        row = connection.execute(
            text(
                """
                INSERT INTO classification_rules (
                    id, tenant_id, company_id, name, priority,
                    conditions_json, actions_json, enabled, version, created_at
                )
                SELECT gen_random_uuid(), CAST(:tid AS uuid), NULL, :name, :priority,
                       CAST(:conditions AS jsonb), CAST(:actions AS jsonb),
                       TRUE, 1, now()
                RETURNING id::text
                """
            ),
            {
                "tid": tenant_id,
                "name": rule["name"],
                "priority": rule["priority"],
                "conditions": json.dumps(rule["conditions"]),
                "actions": json.dumps({"category_code": rule["category_code"]}),
            },
        ).scalar_one()
        connection.commit()
    return str(row)
