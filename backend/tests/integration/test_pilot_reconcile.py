from pathlib import Path
from uuid import uuid4

from tests.integration.conftest import login, open_workspace, pay, register_and_verify

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"
PERIOD = "date_from=2026-10-01&date_to=2026-10-31"


def _company(client, tenant_id: str, name: str) -> str:
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": name, "kind": "company"},
    )
    assert created.status_code == 200, created.text
    company_id = created.json()["id"]
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return company_id


def _wallet(client, company_id: str) -> str:
    created = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Расчётный", "type": "bank", "code": "main"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    wallet_id = created.json()["id"]
    opened = client.post(
        f"/api/v1/wallets/{wallet_id}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+00:00", "amount": "0.00"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert opened.status_code == 200, opened.text
    return wallet_id


def _source(client, company_id: str, wallet_id: str | None, dataset: str, file_format: str) -> str:
    payload = {
        "name": dataset,
        "type": "clientbank" if file_format == "clientbank" else "file",
        "namespace": f"{dataset}-{uuid4().hex[:8]}",
        "format": file_format,
        "dataset": dataset,
    }
    if wallet_id is not None:
        payload["wallet_id"] = wallet_id
    created = client.post(f"/api/v1/companies/{company_id}/sources", json=payload)
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _commit_file(client, company_id: str, source_id: str, name: str) -> None:
    uploaded = client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": source_id},
        files={"upload": (name, (FIXTURES / name).read_bytes(), "application/octet-stream")},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert uploaded.status_code == 200, uploaded.text
    committed = client.post(f"/api/v1/imports/{uploaded.json()['id']}/commit")
    assert committed.status_code == 200, committed.text


def test_two_companies_match_published_fixtures(client, admin, app, fake, tmp_path) -> None:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, "pilot@example.com")
    login(client, "pilot@example.com")
    tenant_id = open_workspace(client, "Пилот")
    pay(client, app, fake, 2, "month")
    alpha = _company(client, tenant_id, "Альфа")
    beta = _company(client, tenant_id, "Бета")
    alpha_wallet = _wallet(client, alpha)
    beta_wallet = _wallet(client, beta)
    cash = _source(client, alpha, alpha_wallet, "cash", "csv")
    sales = _source(client, alpha, None, "revenue", "csv")
    bank = _source(client, beta, beta_wallet, "cash", "clientbank")
    _commit_file(client, alpha, cash, "cash_ok.csv")
    _commit_file(client, alpha, sales, "revenue_ok.csv")
    _commit_file(client, beta, bank, "clientbank_ok.txt")
    unknown = client.post(
        f"/api/v1/companies/{alpha}/imports",
        data={"connection_id": cash},
        files={"upload": ("unknown.txt", (FIXTURES / "unknown.txt").read_bytes(), "text/plain")},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert unknown.status_code == 422
    assert unknown.json()["code"] == "unsupported_format"
    alpha_board = client.get(f"/api/v1/companies/{alpha}/dashboard?{PERIOD}")
    beta_board = client.get(f"/api/v1/companies/{beta}/dashboard?{PERIOD}")
    assert alpha_board.status_code == 200, alpha_board.text
    assert beta_board.status_code == 200, beta_board.text
    assert alpha_board.json()["values"]["cash_total"] == "3000.00"
    assert alpha_board.json()["values"]["revenue"] == "100000.00"
    assert alpha_board.json()["values"]["revenue"] != alpha_board.json()["values"]["cash_total"]
    assert beta_board.json()["values"]["cash_total"] == "1500.00"
    assert beta_board.json()["values"]["revenue"] is None
    group = client.get(f"/api/v1/workspaces/{tenant_id}/group-summary?{PERIOD}")
    assert group.status_code == 200, group.text
    assert group.json()["metrics"]["cash_total"] == "4500.00"
    assert group.json()["metrics"]["revenue"] is None
    assert group.json()["metrics"]["revenue"] != group.json()["metrics"]["cash_total"]
