"""Загрузка профиля cashflow_sections и связывание internal transfer."""

from __future__ import annotations

from fastapi.testclient import TestClient
from tests.synthetic_polygon.harness import ensure_wallet, load_profile
from tests.synthetic_polygon.profiles import CASHFLOW_SECTIONS


def set_cash_sources_coverage(
    client: TestClient,
    company_id: str,
    coverage_through: str,
) -> None:
    """coverage_through на enabled cash-источниках через POST /sources/.../coverage."""
    sources = client.get(f"/api/v1/companies/{company_id}/sources")
    assert sources.status_code == 200, sources.text
    cash_ids = [
        item["id"] for item in sources.json()["sources"] if item.get("dataset") == "cash"
    ]
    assert cash_ids, "нет cash-источников"
    for source_id in cash_ids:
        covered = client.post(
            f"/api/v1/companies/{company_id}/sources/{source_id}/coverage",
            json={"coverage_through": coverage_through},
        )
        assert covered.status_code == 200, covered.text


def load_cashflow_sections_profile(client: TestClient, company_id: str) -> str:
    ensure_wallet(client, company_id, "reserve")
    load_profile(client, company_id, CASHFLOW_SECTIONS)
    txs = client.get(f"/api/v1/companies/{company_id}/transactions?limit=200")
    assert txs.status_code == 200, txs.text
    by_key: dict[tuple[str, str, str], str] = {}
    for item in txs.json()["transactions"]:
        by_key[(item["amount"], item["business_date"], item["wallet_id"])] = item["id"]
    wallets = client.get(f"/api/v1/companies/{company_id}/wallets")
    assert wallets.status_code == 200, wallets.text
    wallet_by_code = {w["code"]: w["id"] for w in wallets.json()["wallets"]}
    out_row = next(row for row in CASHFLOW_SECTIONS.cash if row.external_id == "cfs-xfer-out")
    in_row = next(row for row in CASHFLOW_SECTIONS.cash if row.external_id == "cfs-xfer-in")
    out_id = by_key[(out_row.amount, out_row.business_date, wallet_by_code[out_row.wallet_code])]
    in_id = by_key[(in_row.amount, in_row.business_date, wallet_by_code[in_row.wallet_code])]
    linked = client.post(
        "/api/v1/transfers/link",
        json={"left_id": out_id, "right_id": in_id},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["kind"] == "internal"
    sources = client.get(f"/api/v1/companies/{company_id}/sources")
    assert sources.status_code == 200, sources.text
    cash_sources = [
        item for item in sources.json()["sources"] if item.get("dataset") == "cash"
    ]
    assert len(cash_sources) >= 1
    return cash_sources[0]["id"]
