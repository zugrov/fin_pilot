"""Волна P4.1: флаги НДС в receivable-aging без смены сумм."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import text
from tests.integration.test_org_profile_write_api import (
    _latest_version_id,
    _patch_draft,
    _post_version,
)
from tests.integration.test_revenue_api import _ready


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


def _revenue_source_ready(client, company_id: str, coverage: str = "2026-11-30") -> None:
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


def _receivable(client, company_id: str, as_of: str = "2026-10-31") -> dict:
    resp = client.get(
        f"/api/v1/companies/{company_id}/reports/receivable-aging",
        params={"as_of": as_of},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_receivable_without_profile_vat_unknown(client, admin, app, fake, tmp_path) -> None:
    _, company_id = _ready(client, admin, app, fake, tmp_path, "ar-vat-noprof@example.com")
    _revenue_source_ready(client, company_id)
    _sale_gross(client, company_id, "ar-1", "2026-10-10", "120000.00")
    body = _receivable(client, company_id)
    assert Decimal(body["total_balance"]) == Decimal("120000.00")
    assert "vat_basis_unknown" in body["quality_flags"]
    assert "vat_basis_from_profile" not in body["quality_flags"]


def test_receivable_confirmed_not_applicable_from_profile(
    client, admin, app, fake, tmp_path
) -> None:
    _, company_id = _ready(client, admin, app, fake, tmp_path, "ar-vat-na@example.com")
    _revenue_source_ready(client, company_id)
    _sale_gross(client, company_id, "ar-2", "2026-10-10", "120000.00")
    before = _receivable(client, company_id)
    assert Decimal(before["total_balance"]) == Decimal("120000.00")
    _confirm_profile(client, company_id, vat_status="not_applicable")
    after = _receivable(client, company_id)
    assert Decimal(after["total_balance"]) == Decimal(before["total_balance"])
    assert "vat_basis_unknown" not in after["quality_flags"]
    assert "vat_basis_from_profile" in after["quality_flags"]


def test_receivable_special_rates_keeps_unknown(client, admin, app, fake, tmp_path) -> None:
    _, company_id = _ready(client, admin, app, fake, tmp_path, "ar-vat-spec@example.com")
    _revenue_source_ready(client, company_id)
    _sale_gross(client, company_id, "ar-3", "2026-10-10", "105000.00")
    _confirm_profile(client, company_id, vat_status="special_rates_5_7", tax_system="usn")
    body = _receivable(client, company_id)
    assert "vat_basis_unknown" in body["quality_flags"]
    assert "vat_basis_from_profile" not in body["quality_flags"]


def test_receivable_two_profile_versions_by_month(
    client, admin, app, fake, tmp_path
) -> None:
    _, company_id = _ready(client, admin, app, fake, tmp_path, "ar-vat-2mo@example.com")
    _revenue_source_ready(client, company_id, coverage="2026-12-31")
    _confirm_profile(client, company_id, vat_status="not_applicable")
    with admin.connect() as connection:
        eff = date.fromisoformat(
            connection.execute(
                text(
                    "SELECT effective_from::text FROM organization_profile_versions "
                    "WHERE company_id = :cid ORDER BY effective_from DESC LIMIT 1"
                ),
                {"cid": company_id},
            ).scalar_one()
        )
    if eff.month == 12:
        next_eff = date(eff.year + 1, 1, 1)
    else:
        next_eff = date(eff.year, eff.month + 1, 1)
    created = _post_version(client, company_id, next_eff.isoformat())
    assert created.status_code == 200, created.text
    assert (
        _patch_draft(client, company_id, vat_status="vat_payer", vat_default_rate="22").status_code
        == 200
    )
    version_id = _latest_version_id(client, company_id)
    confirmed = client.post(
        f"/api/v1/companies/{company_id}/organization-profile/versions/{version_id}/confirm",
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert confirmed.status_code == 200, confirmed.text
    overlay_month = next_eff
    if overlay_month.month == 1:
        prior_month = date(overlay_month.year - 1, 12, 1)
    else:
        prior_month = date(overlay_month.year, overlay_month.month - 1, 1)
    _sale_gross(
        client,
        company_id,
        "ar-4a",
        f"{prior_month.year}-{prior_month.month:02d}-05",
        "80000.00",
    )
    _sale_gross(
        client,
        company_id,
        "ar-4b",
        f"{overlay_month.year}-{overlay_month.month:02d}-05",
        "50000.00",
    )
    as_of = date(overlay_month.year, overlay_month.month, 28).isoformat()
    body = _receivable(client, company_id, as_of=as_of)
    assert Decimal(body["total_balance"]) == Decimal("130000.00")
    assert "vat_basis_unknown" in body["quality_flags"]
    assert "vat_basis_from_profile" in body["quality_flags"]
