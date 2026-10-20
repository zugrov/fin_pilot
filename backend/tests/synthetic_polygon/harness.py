"""Загрузка профиля полигона через публичное API (только finpilot_test)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from tests.synthetic_polygon.constants import COVERAGE_THROUGH
from tests.synthetic_polygon.profiles import CompanyProfile

FIXTURES_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_polygon"


def _folder(profile: CompanyProfile) -> Path:
    return FIXTURES_ROOT / profile.slug


def _source(
    client: TestClient,
    company_id: str,
    *,
    dataset: str,
    file_format: str,
    wallet_id: str | None,
    namespace: str,
    source_type: str = "file",
) -> str:
    payload: dict = {
        "name": f"{dataset}-{namespace}",
        "type": source_type,
        "namespace": namespace,
        "format": file_format,
        "dataset": dataset,
    }
    if wallet_id is not None:
        payload["wallet_id"] = wallet_id
    created = client.post(f"/api/v1/companies/{company_id}/sources", json=payload)
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _upload_commit(
    client: TestClient,
    company_id: str,
    source_id: str,
    filename: str,
    content: bytes,
    *,
    preview_token: str | None = None,
) -> dict:
    uploaded = client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": source_id},
        files={"upload": (filename, content, "application/octet-stream")},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    headers: dict[str, str] = {}
    if preview_token:
        headers["Preview-Token"] = preview_token
    elif body.get("preview_token"):
        headers["Preview-Token"] = body["preview_token"]
    committed = client.post(
        f"/api/v1/imports/{body['id']}/commit",
        headers=headers,
    )
    assert committed.status_code == 200, committed.text
    return committed.json()


def ensure_wallet(client: TestClient, company_id: str, code: str = "main") -> str:
    created = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": f"Wallet {code}", "type": "bank", "code": code},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def load_profile(
    client: TestClient,
    company_id: str,
    profile: CompanyProfile,
    *,
    admin: Engine | None = None,
) -> None:
    folder = _folder(profile)
    wallet_id = ensure_wallet(client, company_id)

    if profile.balances:
        bal_source = _source(
            client,
            company_id,
            dataset="balances",
            file_format="csv",
            wallet_id=None,
            namespace=f"{profile.slug}-bal",
        )
        _upload_commit(
            client,
            company_id,
            bal_source,
            "balances.csv",
            (folder / "balances.csv").read_bytes(),
        )

    cash_source = _source(
        client,
        company_id,
        dataset="cash",
        file_format="csv",
        wallet_id=wallet_id,
        namespace=f"{profile.slug}-cash",
    )
    _upload_commit(
        client,
        company_id,
        cash_source,
        "cash.csv",
        (folder / "cash.csv").read_bytes(),
    )

    cb_path = folder / "clientbank.txt"
    if cb_path.is_file() and cb_path.stat().st_size > 0:
        bank_source = _source(
            client,
            company_id,
            dataset="cash",
            file_format="clientbank",
            wallet_id=wallet_id,
            namespace=f"{profile.slug}-cb",
            source_type="clientbank",
        )
        _upload_commit(
            client,
            company_id,
            bank_source,
            "clientbank.txt",
            cb_path.read_bytes(),
        )

    if profile.revenue:
        rev_source = _source(
            client,
            company_id,
            dataset="revenue",
            file_format="csv",
            wallet_id=None,
            namespace=f"{profile.slug}-rev",
        )
        _upload_commit(
            client,
            company_id,
            rev_source,
            "revenue.csv",
            (folder / "revenue.csv").read_bytes(),
        )
        covered = client.post(
            f"/api/v1/companies/{company_id}/sources/{rev_source}/coverage",
            json={"coverage_through": COVERAGE_THROUGH},
        )
        assert covered.status_code == 200, covered.text

    plan_path = folder / "planned_cash.csv"
    if profile.plan and plan_path.is_file():
        plan_source = _source(
            client,
            company_id,
            dataset="plan",
            file_format="csv",
            wallet_id=None,
            namespace=f"{profile.slug}-plan",
        )
        _upload_commit(
            client,
            company_id,
            plan_source,
            "planned_cash.csv",
            plan_path.read_bytes(),
        )

    budget_path = folder / "budget.csv"
    if profile.budget and budget_path.is_file():
        budget_source = _source(
            client,
            company_id,
            dataset="budget",
            file_format="csv",
            wallet_id=None,
            namespace=f"{profile.slug}-budget",
        )
        _upload_commit(
            client,
            company_id,
            budget_source,
            "budget.csv",
            budget_path.read_bytes(),
        )

    if profile.plan_match:
        if admin is None:
            raise ValueError("admin engine required when profile.plan_match is set")
        _apply_plan_matches(client, admin, company_id, profile)


def plan_namespace(profile: CompanyProfile) -> str:
    return f"{profile.slug}-plan"


def plan_event_id(
    admin: Engine,
    company_id: str,
    external_id: str,
    *,
    plan_namespace: str,
) -> str:
    """Резолв только в рамках company + источник dataset=plan и namespace (как SourceIdentity)."""
    with admin.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT p.id::text
                FROM planned_cash_events p
                INNER JOIN source_connections sc ON sc.id = p.source_connection_id
                WHERE p.company_id = :cid
                  AND sc.company_id = :cid
                  AND p.external_id = :eid
                  AND p.status != 'cancelled'
                  AND sc.dataset = 'plan'
                  AND sc.namespace = :ns
                """
            ),
            {"cid": company_id, "eid": external_id, "ns": plan_namespace},
        ).fetchall()
    if len(rows) != 1:
        raise LookupError(
            f"planned_cash_events external_id={external_id!r} company={company_id} "
            f"namespace={plan_namespace!r}: ожидалась 1 строка, найдено {len(rows)}"
        )
    return str(rows[0][0])


def _apply_plan_matches(
    client: TestClient, admin: Engine, company_id: str, profile: CompanyProfile
) -> None:
    cash_rows = {row.external_id: row for row in profile.cash}
    plan_rows = {row.external_id: row for row in profile.plan}

    txs = client.get(f"/api/v1/companies/{company_id}/transactions?limit=200")
    assert txs.status_code == 200, txs.text
    tx_by_amount_date: dict[tuple[str, str], str] = {}
    for item in txs.json()["transactions"]:
        tx_by_amount_date[(item["amount"], item["business_date"])] = item["id"]

    for cash_ext, plan_ext, amount in profile.plan_match:
        cash_row = cash_rows[cash_ext]
        assert plan_ext in plan_rows
        cash_id = tx_by_amount_date[(cash_row.amount, cash_row.business_date)]
        event_id = plan_event_id(
            admin, company_id, plan_ext, plan_namespace=plan_namespace(profile)
        )
        matched = client.post(
            "/api/v1/payment-matches",
            json={
                "company_id": company_id,
                "event_id": event_id,
                "cash_transaction_id": cash_id,
                "amount": amount,
            },
            headers={"Idempotency-Key": uuid4().hex},
        )
        assert matched.status_code == 200, matched.text
