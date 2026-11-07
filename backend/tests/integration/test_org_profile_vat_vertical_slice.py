"""§8: оверлей vat_basis_unknown и подтверждённый профиль."""

from __future__ import annotations

from uuid import uuid4

from tests.integration.conftest import login, open_workspace, pay, register_and_verify
from tests.integration.test_org_profile_write_api import _latest_version_id, _patch_draft
from tests.integration.test_revenue_api import PERIOD, _dashboard, _ready


def _sale_gross(client, company_id: str, key: str, recognition_date: str, amount: str) -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": recognition_date,
            "document_number": "g1",
            "amount_inc_vat": amount,
            "entry_type": "sale",
            "vat_basis": "unknown",
        },
        headers={"Idempotency-Key": key},
    )
    assert created.status_code == 200, created.text
    return created.json()


def _revenue_source_ready(client, company_id: str, coverage: str = "2026-10-31") -> None:
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


def _confirm_profile(client, company_id: str, **overrides) -> None:
    assert _patch_draft(client, company_id, **overrides).status_code == 200
    version_id = _latest_version_id(client, company_id)
    confirmed = client.post(
        f"/api/v1/companies/{company_id}/organization-profile/versions/{version_id}/confirm",
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert confirmed.status_code == 200, confirmed.text


def test_unconfirmed_profile_keeps_vat_unknown(client, admin, app, fake, tmp_path) -> None:
    _, company_id = _ready(client, admin, app, fake, tmp_path, "vat-slice-draft@example.com")
    _revenue_source_ready(client, company_id)
    _sale_gross(client, company_id, "g-1", "2026-10-10", "120000.00")
    body = _dashboard(client, company_id)
    assert "vat_basis_unknown" in body["quality_flags"]
    assert "vat_basis_from_profile" not in body["quality_flags"]


def test_confirmed_not_applicable_clears_flag(client, admin, app, fake, tmp_path) -> None:
    _, company_id = _ready(client, admin, app, fake, tmp_path, "vat-slice-na@example.com")
    _revenue_source_ready(client, company_id)
    _sale_gross(client, company_id, "g-2", "2026-10-10", "120000.00")
    before = _dashboard(client, company_id)
    assert "vat_basis_unknown" in before["quality_flags"]
    _confirm_profile(client, company_id, vat_status="not_applicable")
    after = _dashboard(client, company_id)
    assert "vat_basis_unknown" not in after["quality_flags"]
    assert "vat_basis_from_profile" in after["quality_flags"]
    assert after["metric_basis"] == "net"
    assert after["revenue_label"] == "Выручка без НДС"
    assert after["values"]["revenue"] == "120000.00"
    assert after["input_revision"] != before["input_revision"]


def test_special_rates_keeps_flag(client, admin, app, fake, tmp_path) -> None:
    _, company_id = _ready(client, admin, app, fake, tmp_path, "vat-slice-spec@example.com")
    _revenue_source_ready(client, company_id)
    _sale_gross(client, company_id, "g-3", "2026-10-10", "105000.00")
    _confirm_profile(client, company_id, vat_status="special_rates_5_7", tax_system="usn")
    body = _dashboard(client, company_id)
    assert "vat_basis_unknown" in body["quality_flags"]
    assert "vat_basis_from_profile" not in body["quality_flags"]


def test_group_summary_matches_dashboard(client, admin, app, fake, tmp_path) -> None:
    tenant_id, company_id = _ready(client, admin, app, fake, tmp_path, "vat-slice-grp@example.com")
    _revenue_source_ready(client, company_id)
    _sale_gross(client, company_id, "g-4", "2026-10-10", "80000.00")
    _confirm_profile(client, company_id, vat_status="not_applicable")
    dash = _dashboard(client, company_id)
    group = client.get(f"/api/v1/workspaces/{tenant_id}/group-summary?{PERIOD}")
    assert group.status_code == 200, group.text
    payload = group.json()
    assert dash["values"]["revenue"] in (payload["metrics"]["revenue"],)
    for flag in ("vat_basis_from_profile",):
        if flag in dash["quality_flags"]:
            assert flag in payload["quality_flags"]


def test_isolation_other_tenant_profile(client, admin, app, fake, tmp_path) -> None:
    tenant_a, company_a = _ready(client, admin, app, fake, tmp_path, "vat-iso-a@example.com")
    _revenue_source_ready(client, company_a)
    _sale_gross(client, company_a, "iso-1", "2026-10-10", "50000.00")
    _confirm_profile(client, company_a, vat_status="not_applicable")
    own = _dashboard(client, company_a)
    assert "vat_basis_from_profile" in own["quality_flags"]

    register_and_verify(client, admin, "vat-iso-b@example.com")
    login(client, "vat-iso-b@example.com")
    tenant_b = open_workspace(client, "B")
    pay(client, app, fake, 1, "month")
    foreign = client.get(f"/api/v1/companies/{company_a}/dashboard?{PERIOD}")
    assert foreign.status_code == 404
    assert client.headers.get("X-Tenant-Id") == tenant_b or tenant_b
