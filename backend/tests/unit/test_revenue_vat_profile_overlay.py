from datetime import date
from decimal import Decimal

from app.domain.org_profile.resolution import ResolvedOrganizationProfile
from app.domain.org_profile.revenue_vat_overlay import (
    VAT_BASIS_FROM_PROFILE,
    apply_profile_vat_overlay,
    assess_revenue_with_profile,
)
from app.domain.org_profile.support_matrix import assess_product_support
from app.domain.org_profile.validation import ProfileSnapshot
from app.domain.revenue import NET_LABEL, SOURCE_LABEL, SaleFact, assess_revenue


def _resolved(
    *, vat_status: str, confirmed: bool, article_145: bool = False
) -> ResolvedOrganizationProfile:
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
        version_id="v1",
        effective_from=date(2026, 10, 1),
        snapshot=snapshot,
        is_confirmed=confirmed,
        support=support,
    )


def _gross_sale(day: str = "2026-10-10") -> SaleFact:
    return SaleFact(
        "1",
        "sale",
        "unknown",
        None,
        Decimal("120000.00"),
        date.fromisoformat(day),
    )


def test_assess_revenue_unchanged_without_profile() -> None:
    facts = (_gross_sale(),)
    base = assess_revenue(facts, covered=True)
    view, rev = assess_revenue_with_profile(facts, covered=True, profiles_by_month={})
    assert view == base
    assert rev == ""


def test_not_applicable_confirmed_clears_unknown_flag() -> None:
    facts = (_gross_sale(),)
    profiles = {date(2026, 10, 1): _resolved(vat_status="not_applicable", confirmed=True)}
    view, rev = assess_revenue_with_profile(facts, covered=True, profiles_by_month=profiles)
    assert view.amount == Decimal("120000.00")
    assert view.metric_basis == "net"
    assert view.label == NET_LABEL
    assert "vat_basis_unknown" not in view.quality_flags
    assert VAT_BASIS_FROM_PROFILE in view.quality_flags
    assert rev == "2026-10-01:v1:1"


def test_special_rates_keeps_unknown() -> None:
    facts = (_gross_sale(),)
    profiles = {date(2026, 10, 1): _resolved(vat_status="special_rates_5_7", confirmed=True)}
    view, rev = assess_revenue_with_profile(facts, covered=True, profiles_by_month=profiles)
    assert "vat_basis_unknown" in view.quality_flags
    assert VAT_BASIS_FROM_PROFILE not in view.quality_flags
    assert rev == ""


def test_unconfirmed_profile_no_overlay() -> None:
    facts = (_gross_sale(),)
    profiles = {date(2026, 10, 1): _resolved(vat_status="not_applicable", confirmed=False)}
    view, _ = assess_revenue_with_profile(facts, covered=True, profiles_by_month=profiles)
    assert "vat_basis_unknown" in view.quality_flags


def test_net_row_with_overlaid_unknown_keeps_base_gross() -> None:
    facts = (
        SaleFact(
            "n",
            "sale",
            "net",
            Decimal("100000.00"),
            Decimal("120000.00"),
            date(2026, 10, 5),
        ),
        SaleFact(
            "u",
            "sale",
            "unknown",
            None,
            Decimal("50000.00"),
            date(2026, 11, 5),
        ),
    )
    profiles = {
        date(2026, 10, 1): _resolved(vat_status="vat_payer", confirmed=True),
        date(2026, 11, 1): _resolved(vat_status="not_applicable", confirmed=True),
    }
    base = assess_revenue(facts, covered=True)
    view, rev = assess_revenue_with_profile(facts, covered=True, profiles_by_month=profiles)
    assert base.metric_basis == "source"
    assert view.amount == base.amount
    assert view.label == base.label
    assert view.metric_basis == base.metric_basis
    assert "vat_basis_unknown" in view.quality_flags
    assert VAT_BASIS_FROM_PROFILE in view.quality_flags
    assert rev == "2026-11-01:v1:1"


def test_exemption_without_article_145_no_overlay() -> None:
    facts = (_gross_sale(),)
    profiles = {date(2026, 10, 1): _resolved(vat_status="exemption", confirmed=True)}
    view, rev = assess_revenue_with_profile(facts, covered=True, profiles_by_month=profiles)
    assert view.metric_basis == "source"
    assert VAT_BASIS_FROM_PROFILE not in view.quality_flags
    assert rev == ""


def test_mixed_months_partial_flag() -> None:
    facts = (
        _gross_sale("2026-10-10"),
        SaleFact(
            "2",
            "sale",
            "unknown",
            None,
            Decimal("50000.00"),
            date(2026, 11, 5),
        ),
    )
    profiles = {
        date(2026, 10, 1): _resolved(vat_status="not_applicable", confirmed=True),
        date(2026, 11, 1): _resolved(vat_status="vat_payer", confirmed=True),
    }
    view, rev = assess_revenue_with_profile(facts, covered=True, profiles_by_month=profiles)
    assert view.amount == Decimal("170000.00")
    assert "vat_basis_unknown" in view.quality_flags
    assert VAT_BASIS_FROM_PROFILE in view.quality_flags
    assert view.metric_basis == "source"
    assert view.label == SOURCE_LABEL
    assert "2026-11-01" not in rev


def test_return_with_overlay() -> None:
    facts = (
        _gross_sale(),
        SaleFact(
            "2",
            "return",
            "unknown",
            None,
            Decimal("20000.00"),
            date(2026, 10, 12),
        ),
    )
    profiles = {date(2026, 10, 1): _resolved(vat_status="not_applicable", confirmed=True)}
    view, _ = assess_revenue_with_profile(facts, covered=True, profiles_by_month=profiles)
    assert view.amount == Decimal("100000.00")


def test_exemption_article_145_like_not_applicable() -> None:
    facts = (_gross_sale(),)
    profiles = {
        date(2026, 10, 1): _resolved(
            vat_status="exemption", confirmed=True, article_145=True
        )
    }
    view, rev = assess_revenue_with_profile(facts, covered=True, profiles_by_month=profiles)
    assert VAT_BASIS_FROM_PROFILE in view.quality_flags
    assert "vat_basis_unknown" not in view.quality_flags
    assert rev != ""


def test_apply_overlay_preserves_partial_period() -> None:
    facts = (_gross_sale(),)
    base = assess_revenue(facts, covered=False)
    profiles = {date(2026, 10, 1): _resolved(vat_status="not_applicable", confirmed=True)}
    view, _ = apply_profile_vat_overlay(base, facts, covered=False, profiles_by_month=profiles)
    assert "partial_period" in view.quality_flags
