"""API read-only сверки FA-R03.2 (локальный флаг и company_id)."""

from __future__ import annotations

from tests.integration.conftest import login, open_workspace, pay, register_and_verify


def _company_ready(client, admin, app, fake, email: str) -> str:
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Сверка")
    company = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Фирма", "kind": "company"},
    )
    assert company.status_code == 200
    company_id = company.json()["id"]
    pay(client, app, fake, 1, "month")
    assert client.post(f"/api/v1/billing/companies/{company_id}/activate").status_code == 200
    return company_id


def test_reconciliation_flag_off_returns_404(client, admin, app, fake) -> None:
    company_id = _company_ready(client, admin, app, fake, "reconcile-off@example.com")
    response = client.get(
        f"/api/v1/companies/{company_id}/reconciliation/bank-card-51",
        params={"year": 2026, "month": 9},
    )
    assert response.status_code == 404


def test_reconciliation_wrong_company_returns_404(client, admin, app, fake) -> None:
    company_id = _company_ready(client, admin, app, fake, "reconcile-wrong@example.com")
    other_id = "00000000-0000-4000-8000-000000000001"
    app.state.settings = app.state.settings.model_copy(
        update={
            "fa_r03_local_reconciliation_enabled": True,
            "fa_r03_local_samples_root": "/tmp/unused",
            "fa_r03_local_reconciliation_company_id": other_id,
        }
    )
    response = client.get(
        f"/api/v1/companies/{company_id}/reconciliation/bank-card-51",
        params={"year": 2026, "month": 9},
    )
    assert response.status_code == 404


def test_reconciliation_enabled_matching_company(client, admin, app, fake, tmp_path) -> None:
    company_id = _company_ready(client, admin, app, fake, "reconcile-ok@example.com")
    app.state.settings = app.state.settings.model_copy(
        update={
            "fa_r03_local_reconciliation_enabled": True,
            "fa_r03_local_samples_root": str(tmp_path),
            "fa_r03_local_reconciliation_company_id": company_id,
        }
    )
    response = client.get(
        f"/api/v1/companies/{company_id}/reconciliation/bank-card-51",
        params={"year": 2026, "month": 9},
    )
    assert response.status_code == 503
