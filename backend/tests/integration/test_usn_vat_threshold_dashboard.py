"""P4 волна 2: блок vat_threshold в dashboard."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from tests.integration.test_org_profile_write_api import _latest_version_id, _patch_draft
from tests.integration.test_revenue_api import PERIOD, _dashboard, _ready


def _revenue_source(client, company_id: str, coverage: str = "2026-12-31") -> None:
    source = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Продажи",
            "type": "file",
            "namespace": "sales",
            "format": "csv",
            "dataset": "revenue",
            "vat_basis": "unknown",
        },
    )
    assert source.status_code == 200, source.text
    covered = client.post(
        f"/api/v1/companies/{company_id}/sources/{source.json()['id']}/coverage",
        json={"coverage_through": coverage},
    )
    assert covered.status_code == 200, covered.text


def _sale(client, company_id: str, key: str, day: str, amount: str) -> None:
    created = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": day,
            "document_number": "s1",
            "amount_inc_vat": amount,
            "entry_type": "sale",
            "vat_basis": "unknown",
        },
        headers={"Idempotency-Key": key},
    )
    assert created.status_code == 200, created.text


def _confirm_na(client, company_id: str) -> None:
    patched = _patch_draft(client, company_id, vat_status="not_applicable", tax_system="usn")
    assert patched.status_code == 200
    version_id = _latest_version_id(client, company_id)
    confirmed = client.post(
        f"/api/v1/companies/{company_id}/organization-profile/versions/{version_id}/confirm",
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert confirmed.status_code == 200, confirmed.text


def test_no_block_without_confirmed_profile(client, admin, app, fake, tmp_path) -> None:
    _, company_id = _ready(client, admin, app, fake, tmp_path, "vath-noconf@example.com")
    _revenue_source(client, company_id)
    _sale(client, company_id, "vt-1", "2026-10-10", "100000.00")
    body = _dashboard(client, company_id)
    assert "vat_threshold" not in body


def test_no_block_for_vat_payer(client, admin, app, fake, tmp_path) -> None:
    _, company_id = _ready(client, admin, app, fake, tmp_path, "vath-payer@example.com")
    _revenue_source(client, company_id)
    payer = _patch_draft(
        client,
        company_id,
        vat_status="vat_payer",
        vat_default_rate="22",
        tax_system="usn",
    )
    assert payer.status_code == 200
    version_id = _latest_version_id(client, company_id)
    confirmed = client.post(
        f"/api/v1/companies/{company_id}/organization-profile/versions/{version_id}/confirm",
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert confirmed.status_code == 200, confirmed.text
    _sale(client, company_id, "vt-2", "2026-10-10", "100000.00")
    body = _dashboard(client, company_id)
    assert "vat_threshold" not in body


def test_block_not_applicable_approaching(client, admin, app, fake, tmp_path) -> None:
    _, company_id = _ready(client, admin, app, fake, tmp_path, "vath-approach@example.com")
    _revenue_source(client, company_id)
    _confirm_na(client, company_id)
    _sale(client, company_id, "vt-3", "2026-10-05", "16500000.00")
    body = _dashboard(client, company_id)
    block = body.get("vat_threshold")
    assert block is not None
    assert block["status"] == "approaching"
    assert Decimal(block["ytd_revenue"]) == Decimal("16500000.00")
    assert block["threshold"] == "20000000.00"
    assert block["disclaimer"] == "usn_accrual_vs_cash"


def test_dashboard_input_revision_changes_with_threshold(
    client, admin, app, fake, tmp_path
) -> None:
    _, company_id = _ready(client, admin, app, fake, tmp_path, "vath-rev@example.com")
    _revenue_source(client, company_id)
    without = _dashboard(client, company_id)
    _confirm_na(client, company_id)
    with_block = _dashboard(client, company_id)
    assert "vat_threshold" in with_block
    assert without["input_revision"] != with_block["input_revision"]


def test_no_block_when_norms_needs_review(client, admin, app, fake, tmp_path) -> None:
    _, company_id = _ready(client, admin, app, fake, tmp_path, "vath-norm-nr@example.com")
    _revenue_source(client, company_id, coverage="2030-12-31")
    _confirm_na(client, company_id)
    response = client.get(
        f"/api/v1/companies/{company_id}/dashboard",
        params={"date_from": "2030-01-01", "date_to": "2030-01-31"},
    )
    assert response.status_code == 200, response.text
    assert "vat_threshold" not in response.json()


def test_exceeded_status_in_dashboard(client, admin, app, fake, tmp_path) -> None:
    _, company_id = _ready(client, admin, app, fake, tmp_path, "vath-exceeded@example.com")
    _revenue_source(client, company_id)
    _confirm_na(client, company_id)
    _sale(client, company_id, "vt-ex", "2026-10-05", "21000000.00")
    body = _dashboard(client, company_id)
    block = body["vat_threshold"]
    assert block["status"] == "exceeded"
    assert block["exceeded_month"] == "2026-10"
    assert block["obligation_from"] == "2026-11-01"


def test_exactly_at_threshold_not_exceeded(client, admin, app, fake, tmp_path) -> None:
    _, company_id = _ready(client, admin, app, fake, tmp_path, "vath-eq@example.com")
    _revenue_source(client, company_id)
    _confirm_na(client, company_id)
    _sale(client, company_id, "vt-eq", "2026-10-05", "20000000.00")
    body = _dashboard(client, company_id)
    block = body["vat_threshold"]
    assert block["status"] == "approaching"
    assert block["ytd_revenue"] == "20000000.00"
    assert block["exceeded_month"] is None


def test_past_year_dashboard_without_norms_has_no_block(
    client, admin, app, fake, tmp_path
) -> None:
    """as_of = date_to периода; норм на 2025-12-31 в справочнике нет — блок не добавляем."""
    _, company_id = _ready(client, admin, app, fake, tmp_path, "vath-2025@example.com")
    _revenue_source(client, company_id, coverage="2025-12-31")
    _confirm_na(client, company_id)
    _sale(client, company_id, "vt-25", "2025-12-10", "1000000.00")
    response = client.get(
        f"/api/v1/companies/{company_id}/dashboard",
        params={"date_from": "2025-12-01", "date_to": "2025-12-31"},
    )
    assert response.status_code == 200, response.text
    assert "vat_threshold" not in response.json()


def test_dashboard_period_end_year_drives_ytd_and_norms(
    client, admin, app, fake, tmp_path
) -> None:
    """Период в 2027: YTD с 2027-01-01, порог из норм на date_to."""
    _, company_id = _ready(client, admin, app, fake, tmp_path, "vath-2027@example.com")
    _revenue_source(client, company_id, coverage="2027-12-31")
    _confirm_na(client, company_id)
    _sale(client, company_id, "vt-27", "2027-06-15", "500000.00")
    response = client.get(
        f"/api/v1/companies/{company_id}/dashboard",
        params={"date_from": "2027-06-01", "date_to": "2027-06-30"},
    )
    assert response.status_code == 200, response.text
    block = response.json()["vat_threshold"]
    assert block["as_of"] == "2027-06-30"
    assert block["threshold"] == "20000000.00"
    assert Decimal(block["ytd_revenue"]) == Decimal("500000.00")


def test_tenant_isolation_vat_threshold_and_revision(client, admin, app, fake, tmp_path) -> None:
    from fastapi.testclient import TestClient
    from tests.integration.conftest import login, open_workspace, pay, register_and_verify

    _, company_a = _ready(client, admin, app, fake, tmp_path, "vath-iso-a@example.com")
    _revenue_source(client, company_a)
    _confirm_na(client, company_a)
    _sale(client, company_a, "vt-a", "2026-10-05", "16500000.00")
    dash_a = _dashboard(client, company_a)
    assert dash_a["vat_threshold"]["status"] == "approaching"
    rev_a = dash_a["input_revision"]

    client_b = TestClient(client.app)
    register_and_verify(client_b, admin, "vath-iso-b@example.com")
    login(client_b, "vath-iso-b@example.com")
    tenant_b = open_workspace(client_b, "B")
    pay(client_b, app, fake, 1, "month")
    created = client_b.post(
        f"/api/v1/workspaces/{tenant_b}/companies",
        json={"name": "B", "kind": "company", "timezone": "Europe/Moscow"},
    )
    assert created.status_code == 200, created.text
    company_b = created.json()["id"]
    client_b.post(f"/api/v1/billing/companies/{company_b}/activate")

    _revenue_source(client_b, company_b)
    assert (
        _patch_draft(client_b, company_b, vat_status="not_applicable", tax_system="usn").status_code
        == 200
    )
    version_id = _latest_version_id(client_b, company_b)
    confirmed = client_b.post(
        f"/api/v1/companies/{company_b}/organization-profile/versions/{version_id}/confirm",
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert confirmed.status_code == 200, confirmed.text
    _sale(client_b, company_b, "vt-b1", "2026-10-10", "50000.00")
    dash_b = client_b.get(f"/api/v1/companies/{company_b}/dashboard?{PERIOD}")
    block_b = dash_b.json()["vat_threshold"]
    assert block_b["status"] == "ok"
    rev_b = dash_b.json()["input_revision"]
    assert rev_b != rev_a

    dash_b_repeat = client_b.get(f"/api/v1/companies/{company_b}/dashboard?{PERIOD}")
    assert dash_b_repeat.json()["input_revision"] == rev_b
    assert Decimal(dash_b_repeat.json()["vat_threshold"]["ytd_revenue"]) == Decimal("50000.00")

    foreign = client_b.get(f"/api/v1/companies/{company_a}/dashboard?{PERIOD}")
    assert foreign.status_code in (403, 404)
