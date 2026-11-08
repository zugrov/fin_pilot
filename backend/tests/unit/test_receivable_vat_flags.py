from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.domain.org_profile.resolution import ResolvedOrganizationProfile
from app.domain.org_profile.revenue_vat_overlay import (
    VAT_BASIS_FROM_PROFILE,
    receivable_vat_quality_flags,
    row_vat_basis_unknown,
)
from app.domain.org_profile.support_matrix import assess_product_support
from app.domain.org_profile.validation import ProfileSnapshot


def _entry(*, vat_basis: str, amount_ex_vat: Decimal | None, day: str = "2026-10-10"):
    return SimpleNamespace(
        vat_basis=vat_basis,
        amount_ex_vat=amount_ex_vat,
        recognition_date=date.fromisoformat(day),
    )


def _resolved(*, vat_status: str, confirmed: bool, article_145: bool = False):
    snapshot = ProfileSnapshot(
        vat_status=vat_status,
        vat_exemption_article_145=article_145,
    )
    support = assess_product_support(
        org_form=snapshot.org_form,
        tax_system=snapshot.tax_system,
        accounting_source=snapshot.accounting_source,
    )
    return ResolvedOrganizationProfile(
        version_id=str(uuid4()),
        effective_from=date(2026, 10, 1),
        snapshot=snapshot,
        is_confirmed=confirmed,
        support=support,
    )


def test_row_vat_basis_unknown_gross_only() -> None:
    assert row_vat_basis_unknown(vat_basis="unknown", amount_ex_vat=None) is True
    assert row_vat_basis_unknown(vat_basis="net", amount_ex_vat=Decimal("100")) is False


def test_receivable_flags_none_for_net_rows() -> None:
    entry = _entry(vat_basis="net", amount_ex_vat=Decimal("100"))
    assert receivable_vat_quality_flags((entry,), profiles_by_month={}) == []


def test_receivable_flags_unknown_without_profile() -> None:
    entry = _entry(vat_basis="unknown", amount_ex_vat=None)
    flags = receivable_vat_quality_flags((entry,), profiles_by_month={})
    assert flags == ["vat_basis_unknown"]


def test_receivable_flags_from_profile_when_confirmed() -> None:
    entry = _entry(vat_basis="unknown", amount_ex_vat=None)
    profiles = {date(2026, 10, 1): _resolved(vat_status="not_applicable", confirmed=True)}
    flags = receivable_vat_quality_flags((entry,), profiles_by_month=profiles)
    assert flags == [VAT_BASIS_FROM_PROFILE]


def test_receivable_flags_special_rates_keeps_unknown() -> None:
    entry = _entry(vat_basis="unknown", amount_ex_vat=None)
    profiles = {date(2026, 10, 1): _resolved(vat_status="special_rates_5_7", confirmed=True)}
    flags = receivable_vat_quality_flags((entry,), profiles_by_month=profiles)
    assert flags == ["vat_basis_unknown"]


def test_receivable_flags_mixed_months_both_flags() -> None:
    oct_entry = _entry(vat_basis="unknown", amount_ex_vat=None, day="2026-10-10")
    nov_entry = _entry(vat_basis="unknown", amount_ex_vat=None, day="2026-11-05")
    profiles = {
        date(2026, 10, 1): _resolved(vat_status="not_applicable", confirmed=True),
        date(2026, 11, 1): _resolved(vat_status="vat_payer", confirmed=True),
    }
    flags = receivable_vat_quality_flags((oct_entry, nov_entry), profiles_by_month=profiles)
    assert "vat_basis_unknown" in flags
    assert VAT_BASIS_FROM_PROFILE in flags
