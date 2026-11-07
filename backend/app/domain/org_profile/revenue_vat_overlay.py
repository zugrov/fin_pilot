"""Оверлей профиля на оценку выручки (vertical slice §8, ADR-003 §5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.money import money
from app.domain.org_profile.constants import VAT_STATUSES
from app.domain.org_profile.resolution import ResolvedOrganizationProfile
from app.domain.revenue import NET_LABEL, SOURCE_LABEL, RevenueView, SaleFact, assess_revenue

VAT_BASIS_FROM_PROFILE = "vat_basis_from_profile"
NOT_APPLICABLE = "not_applicable"
EXEMPTION = "exemption"


def month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def months_in_range(date_from: date, date_to: date) -> list[date]:
    if date_to < date_from:
        return []
    result: list[date] = []
    year, month = date_from.year, date_from.month
    end_key = (date_to.year, date_to.month)
    while (year, month) <= end_key:
        result.append(date(year, month, 1))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return result


def _overlay_applies(resolved: ResolvedOrganizationProfile | None) -> bool:
    if resolved is None or not resolved.is_confirmed:
        return False
    status = resolved.snapshot.vat_status
    if status not in VAT_STATUSES:
        return False
    if status == NOT_APPLICABLE:
        return True
    if status == EXEMPTION and resolved.snapshot.vat_exemption_article_145 is True:
        return True
    return False


def _row_unknown(fact: SaleFact) -> bool:
    return fact.vat_basis != "net" or fact.amount_ex_vat is None


def _signed_row(fact: SaleFact, *, treat_gross_as_net: bool) -> Decimal:
    if treat_gross_as_net:
        amount = fact.amount_inc_vat
    elif not _row_unknown(fact):
        amount = fact.amount_ex_vat
    else:
        amount = fact.amount_inc_vat
    if amount is None:
        return Decimal("0")
    signed = -amount if fact.entry_type == "return" else amount
    return money(signed)


@dataclass(frozen=True)
class OverlayTrace:
    revenue_profile_revision: str


def apply_profile_vat_overlay(
    base: RevenueView,
    facts: tuple[SaleFact, ...],
    *,
    covered: bool,
    profiles_by_month: dict[date, ResolvedOrganizationProfile | None],
) -> tuple[RevenueView, OverlayTrace]:
    if not facts:
        return base, OverlayTrace(revenue_profile_revision="")

    overlay_months: dict[date, str] = {}
    total = Decimal("0")
    any_overlay = False
    any_unknown_without_overlay = False

    for fact in facts:
        row_month = None
        if fact.recognition_date is not None:
            row_month = month_start(fact.recognition_date)
        resolved = profiles_by_month.get(row_month) if row_month else None
        use_overlay = _overlay_applies(resolved) and _row_unknown(fact)
        if use_overlay:
            any_overlay = True
            assert resolved is not None
            overlay_months[row_month] = resolved.version_id
            total = money(total + _signed_row(fact, treat_gross_as_net=True))
        elif _row_unknown(fact):
            any_unknown_without_overlay = True
            total = money(total + _signed_row(fact, treat_gross_as_net=False))
        else:
            total = money(total + _signed_row(fact, treat_gross_as_net=False))

    if not any_overlay:
        return base, OverlayTrace(revenue_profile_revision="")

    flags = [item for item in base.quality_flags if item != "vat_basis_unknown"]
    if any_unknown_without_overlay:
        if "vat_basis_unknown" not in flags:
            flags.append("vat_basis_unknown")
        label = SOURCE_LABEL
        basis = "source"
    else:
        label = NET_LABEL
        basis = "net"
    if VAT_BASIS_FROM_PROFILE not in flags:
        flags.append(VAT_BASIS_FROM_PROFILE)

    revision_parts = [
        f"{month.isoformat()}:{version_id}:1"
        for month, version_id in sorted(overlay_months.items())
    ]
    view = RevenueView(
        amount=total,
        label=label,
        metric_basis=basis,
        quality_flags=tuple(flags),
        entry_ids=base.entry_ids,
    )
    if not covered and "partial_period" not in view.quality_flags:
        flags_list = list(view.quality_flags)
        flags_list.insert(0, "partial_period")
        view = RevenueView(
            amount=view.amount,
            label=view.label,
            metric_basis=view.metric_basis,
            quality_flags=tuple(flags_list),
            entry_ids=view.entry_ids,
        )
    return view, OverlayTrace(revenue_profile_revision="|".join(revision_parts))


def assess_revenue_with_profile(
    facts: tuple[SaleFact, ...],
    *,
    covered: bool,
    profiles_by_month: dict[date, ResolvedOrganizationProfile | None],
) -> tuple[RevenueView, str]:
    base = assess_revenue(facts, covered=covered)
    view, trace = apply_profile_vat_overlay(
        base, facts, covered=covered, profiles_by_month=profiles_by_month
    )
    return view, trace.revenue_profile_revision
