"""Оверлей профиля на оценку выручки (vertical slice §8, ADR-003 §5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.domain.money import money
from app.domain.org_profile.constants import VAT_STATUSES
from app.domain.org_profile.resolution import ResolvedOrganizationProfile
from app.domain.revenue import NET_LABEL, RevenueView, SaleFact, assess_revenue


class ReceivableVatRow(Protocol):
    vat_basis: str
    amount_ex_vat: Decimal | None
    recognition_date: date | None

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


def profile_vat_overlay_applies(resolved: ResolvedOrganizationProfile | None) -> bool:
    """Подтверждённый профиль, при котором gross-only трактуется как net (§8)."""
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


_overlay_applies = profile_vat_overlay_applies


def row_vat_basis_unknown(*, vat_basis: str, amount_ex_vat: Decimal | None) -> bool:
    return vat_basis != "net" or amount_ex_vat is None


def _row_unknown(fact: SaleFact) -> bool:
    return row_vat_basis_unknown(vat_basis=fact.vat_basis, amount_ex_vat=fact.amount_ex_vat)


def _signed_row(fact: SaleFact, *, treat_gross_as_net: bool) -> Decimal:
    if treat_gross_as_net:
        amount = fact.amount_inc_vat
    elif not _row_unknown(fact) and fact.amount_ex_vat is not None:
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


def _append_vat_from_profile(flags: tuple[str, ...]) -> tuple[str, ...]:
    items = list(flags)
    if VAT_BASIS_FROM_PROFILE not in items:
        items.append(VAT_BASIS_FROM_PROFILE)
    return tuple(items)


def _with_partial_period(view: RevenueView, *, covered: bool) -> RevenueView:
    if covered or "partial_period" in view.quality_flags:
        return view
    flags_list = list(view.quality_flags)
    flags_list.insert(0, "partial_period")
    return RevenueView(
        amount=view.amount,
        label=view.label,
        metric_basis=view.metric_basis,
        quality_flags=tuple(flags_list),
        entry_ids=view.entry_ids,
    )


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
    any_overlay = False
    any_unknown_without_overlay = False
    has_net_row = False

    for fact in facts:
        if not _row_unknown(fact):
            has_net_row = True
        row_month: date | None = None
        if fact.recognition_date is not None:
            row_month = month_start(fact.recognition_date)
        resolved = profiles_by_month.get(row_month) if row_month is not None else None
        use_overlay = _overlay_applies(resolved) and _row_unknown(fact)
        if (
            use_overlay
            and resolved is not None
            and row_month is not None
        ):
            any_overlay = True
            overlay_months[row_month] = resolved.version_id
        elif _row_unknown(fact):
            any_unknown_without_overlay = True

    if not any_overlay:
        return base, OverlayTrace(revenue_profile_revision="")

    revision_parts = [
        f"{month.isoformat()}:{version_id}:1"
        for month, version_id in sorted(overlay_months.items())
    ]
    trace = OverlayTrace(revenue_profile_revision="|".join(revision_parts))

    keep_base_metrics = any_unknown_without_overlay or (
        has_net_row and base.metric_basis == "source"
    )
    if keep_base_metrics:
        view = RevenueView(
            amount=base.amount,
            label=base.label,
            metric_basis=base.metric_basis,
            quality_flags=_append_vat_from_profile(base.quality_flags),
            entry_ids=base.entry_ids,
        )
        return _with_partial_period(view, covered=covered), trace

    total = Decimal("0")
    for fact in facts:
        fact_month: date | None = None
        if fact.recognition_date is not None:
            fact_month = month_start(fact.recognition_date)
        resolved = profiles_by_month.get(fact_month) if fact_month is not None else None
        treat_as_net = (
            _row_unknown(fact)
            and _overlay_applies(resolved)
            and resolved is not None
            and fact_month is not None
        )
        total = money(total + _signed_row(fact, treat_gross_as_net=treat_as_net))

    flags = [item for item in base.quality_flags if item != "vat_basis_unknown"]
    view = RevenueView(
        amount=total,
        label=NET_LABEL,
        metric_basis="net",
        quality_flags=_append_vat_from_profile(tuple(flags)),
        entry_ids=base.entry_ids,
    )
    return _with_partial_period(view, covered=covered), trace


def receivable_vat_quality_flags(
    entries: tuple[ReceivableVatRow, ...],
    *,
    profiles_by_month: dict[date, ResolvedOrganizationProfile | None],
) -> list[str]:
    """Флаги НДС для дебиторки: суммы не меняем, только quality_flags (FA-R06.1 §4.6)."""
    gross = [
        item
        for item in entries
        if row_vat_basis_unknown(vat_basis=item.vat_basis, amount_ex_vat=item.amount_ex_vat)
    ]
    if not gross:
        return []

    any_overlay = False
    any_unknown_without_overlay = False
    for entry in gross:
        if entry.recognition_date is None:
            any_unknown_without_overlay = True
            continue
        row_month = month_start(entry.recognition_date)
        resolved = profiles_by_month.get(row_month)
        if profile_vat_overlay_applies(resolved):
            any_overlay = True
        else:
            any_unknown_without_overlay = True

    flags: list[str] = []
    if any_unknown_without_overlay:
        flags.append("vat_basis_unknown")
    if any_overlay:
        flags.append(VAT_BASIS_FROM_PROFILE)
    return flags


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
