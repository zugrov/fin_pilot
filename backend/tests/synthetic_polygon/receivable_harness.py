"""Загрузка профиля receivable_demo и явные revenue-cash matches."""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient
from tests.synthetic_polygon.harness import load_profile
from tests.synthetic_polygon.profiles import RECEIVABLE_DEMO
from tests.synthetic_polygon.receivable_oracle import MATCH_PLAN


def load_receivable_demo_profile(client: TestClient, company_id: str) -> None:
    load_profile(client, company_id, RECEIVABLE_DEMO)


def _entry_id_by_external_id(client: TestClient, company_id: str, external_id: str) -> str:
    listed = client.get(f"/api/v1/companies/{company_id}/revenue")
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json()["entries"] if item["external_id"] == external_id)
    return row["id"]


def _cash_id_by_external_id(client: TestClient, company_id: str, external_id: str) -> str:
    cash_row = next(row for row in RECEIVABLE_DEMO.cash if row.external_id == external_id)
    listed = client.get(f"/api/v1/companies/{company_id}/transactions?limit=200")
    assert listed.status_code == 200, listed.text
    for item in listed.json()["transactions"]:
        if item["amount"] == cash_row.amount and item["business_date"] == cash_row.business_date:
            return item["id"]
    raise LookupError(f"cash transaction not found for {external_id}")


def apply_receivable_demo_matches(client: TestClient, company_id: str) -> None:
    for entry_ext, cash_ext, amount in MATCH_PLAN:
        entry_id = _entry_id_by_external_id(client, company_id, entry_ext)
        cash_id = _cash_id_by_external_id(client, company_id, cash_ext)
        matched = client.post(
            "/api/v1/revenue-cash-matches",
            json={
                "company_id": company_id,
                "revenue_entry_id": entry_id,
                "cash_transaction_id": cash_id,
                "amount": amount,
            },
            headers={"Idempotency-Key": uuid4().hex},
        )
        assert matched.status_code == 200, matched.text
