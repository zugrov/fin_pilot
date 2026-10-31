"""Одно определение «неразнесённой» операции: сводка и ОДДС совпадают."""

from __future__ import annotations

from uuid import uuid4

import pytest
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import (
    freeze,
    login,
    open_workspace,
    pay,
    register_and_verify,
)
from tests.synthetic_polygon.cashflow_oracle import section_amounts
from tests.synthetic_polygon.constants import polygon_frozen_moment

HEADER = (
    "external_id,wallet_code,business_date,direction,amount,currency,"
    "counterparty_inn,counterparty_name,description,document_number,category_code,direction_code\n"
)
PERIOD = ("2026-10-01", "2026-10-31")
PERIOD_QUERY = f"date_from={PERIOD[0]}&date_to={PERIOD[1]}"


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
    tenant_id = open_workspace(client, "Unclassified Co")
    pay(client, app, fake, 1, "month")
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Unclassified Co", "kind": "company", "timezone": "Europe/Moscow"},
    )
    assert created.status_code == 200, created.text
    company_id = created.json()["id"]
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return company_id


def _wallet(client, company_id: str, name: str, code: str) -> str:
    created = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": name, "type": "bank", "code": code},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _import_rows(client, company_id: str, wallet_id: str, body: str) -> None:
    source = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": f"src-{uuid4().hex[:8]}",
            "type": "file",
            "namespace": uuid4().hex[:8],
            "format": "csv",
            "encoding": "utf-8",
            "wallet_id": wallet_id,
        },
    )
    assert source.status_code == 200, source.text
    uploaded = client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": source.json()["id"]},
        files={"upload": ("rows.csv", (HEADER + body).encode(), "application/octet-stream")},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert uploaded.status_code == 200, uploaded.text
    committed = client.post(f"/api/v1/imports/{uploaded.json()['id']}/commit")
    assert committed.status_code == 200, committed.text


def _summary(client, company_id: str) -> dict:
    response = client.get(
        f"/api/v1/companies/{company_id}/transactions/unclassified/summary?{PERIOD_QUERY}"
    )
    assert response.status_code == 200, response.text
    return response.json()


def _cashflow(client, company_id: str) -> dict:
    response = client.get(f"/api/v1/companies/{company_id}/cashflow?{PERIOD_QUERY}")
    assert response.status_code == 200, response.text
    return response.json()


def test_internal_transfer_without_category_is_not_unclassified(
    client, admin, app, fake, tmp_path
) -> None:
    """Внутренний перевод без категории: ОДДС его не показывает — и сводка тоже."""
    freeze(app, polygon_frozen_moment())
    company_id = _company(client, admin, app, fake, tmp_path, "uncls-internal@example.com")
    main_id = _wallet(client, company_id, "Main", "main")
    reserve_id = _wallet(client, company_id, "Reserve", "reserve")
    _import_rows(
        client,
        company_id,
        main_id,
        "tr-out,main,2026-10-16,out,2000.00,RUB,,,На резерв,,,\n",
    )
    _import_rows(
        client,
        company_id,
        reserve_id,
        "tr-in,reserve,2026-10-16,in,2000.00,RUB,,,С основного,,,\n",
    )

    before_summary = _summary(client, company_id)
    before_cashflow = _cashflow(client, company_id)
    assert before_summary["out"] == {"count": 1, "amount": "2000.00"}
    assert before_summary["in"] == {"count": 1, "amount": "2000.00"}
    assert section_amounts(before_cashflow)["unmapped"] == ("2000.00", "2000.00")

    txs = client.get(f"/api/v1/companies/{company_id}/transactions?limit=50")
    assert txs.status_code == 200, txs.text
    ids = {item["direction"]: item["id"] for item in txs.json()["transactions"]}
    linked = client.post(
        "/api/v1/transfers/link",
        json={"left_id": ids["out"], "right_id": ids["in"]},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["kind"] == "internal"

    after_cashflow = _cashflow(client, company_id)
    after_summary = _summary(client, company_id)
    listed = client.get(f"/api/v1/companies/{company_id}/transactions/unclassified?{PERIOD_QUERY}")
    assert listed.status_code == 200, listed.text

    assert section_amounts(after_cashflow)["unmapped"] == ("0.00", "0.00")
    assert after_summary["in"] == {"count": 0, "amount": "0.00"}
    assert after_summary["out"] == {"count": 0, "amount": "0.00"}
    assert listed.json()["transactions"] == []
