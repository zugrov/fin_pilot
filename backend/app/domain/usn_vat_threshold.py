"""Мониторинг порога НДС при УСН (P4 волна 2, ADR-003 §4.1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.money import money, money_str
from app.domain.org_profile.revenue_vat_overlay import month_start

DISCLAIMER_USN_ACCRUAL_VS_CASH = "usn_accrual_vs_cash"
APPROACHING_RATIO = Decimal("0.80")
THRESHOLD_NORM_STATUSES = frozenset({"confirmed", "partially_confirmed"})


@dataclass(frozen=True)
class VatThresholdAssessment:
    status: str
    ytd_revenue: Decimal
    threshold: Decimal
    percent: Decimal
    as_of: date
    exceeded_month: date | None
    obligation_from: date | None
    partial: bool
    disclaimer: str


def _signed_gross(amount_inc_vat: Decimal, entry_type: str) -> Decimal:
    if entry_type == "return":
        return money(-amount_inc_vat)
    return money(amount_inc_vat)


def _month_totals_gross(
    rows: tuple[tuple[date, str, Decimal], ...],
    *,
    year: int,
    through_month: int,
) -> dict[date, Decimal]:
    totals: dict[date, Decimal] = {}
    for recognition_date, entry_type, amount_inc_vat in rows:
        if recognition_date.year != year:
            continue
        if recognition_date.month > through_month:
            continue
        key = month_start(recognition_date)
        prior = totals.get(key, Decimal("0"))
        totals[key] = money(prior + _signed_gross(amount_inc_vat, entry_type))
    return totals


def _exceeded_month(
    month_totals: dict[date, Decimal],
    *,
    year: int,
    through_month: int,
    threshold: Decimal,
) -> date | None:
    cumulative = Decimal("0")
    for month in range(1, through_month + 1):
        key = date(year, month, 1)
        cumulative = money(cumulative + month_totals.get(key, Decimal("0")))
        if cumulative > threshold:
            return key
    return None


def _obligation_from(exceeded_month: date | None) -> date | None:
    if exceeded_month is None:
        return None
    if exceeded_month.month == 12:
        return date(exceeded_month.year + 1, 1, 1)
    return date(exceeded_month.year, exceeded_month.month + 1, 1)


def _percent_of_threshold(ytd: Decimal, threshold: Decimal) -> Decimal:
    if threshold <= 0:
        return Decimal("0")
    return money((ytd / threshold) * Decimal("100"))


def assess_usn_vat_threshold(
    rows: tuple[tuple[date, str, Decimal], ...],
    *,
    as_of: date,
    threshold: Decimal,
    partial: bool,
) -> VatThresholdAssessment:
    year = as_of.year
    month_totals = _month_totals_gross(rows, year=year, through_month=as_of.month)
    ytd = money(sum(month_totals.values(), Decimal("0")))
    exceeded = _exceeded_month(
        month_totals,
        year=year,
        through_month=as_of.month,
        threshold=threshold,
    )
    obligation = _obligation_from(exceeded)
    percent = _percent_of_threshold(ytd, threshold)
    ratio = ytd / threshold if threshold > 0 else Decimal("0")
    if ytd > threshold:
        status = "exceeded"
    elif ratio >= APPROACHING_RATIO:
        status = "approaching"
    else:
        status = "ok"
    return VatThresholdAssessment(
        status=status,
        ytd_revenue=ytd,
        threshold=threshold,
        percent=percent,
        as_of=as_of,
        exceeded_month=exceeded,
        obligation_from=obligation,
        partial=partial,
        disclaimer=DISCLAIMER_USN_ACCRUAL_VS_CASH,
    )


def vat_threshold_to_payload(view: VatThresholdAssessment) -> dict:
    return {
        "status": view.status,
        "ytd_revenue": money_str(view.ytd_revenue),
        "threshold": money_str(view.threshold),
        "percent": money_str(view.percent),
        "as_of": view.as_of.isoformat(),
        "exceeded_month": (
            None if view.exceeded_month is None else view.exceeded_month.isoformat()[:7]
        ),
        "obligation_from": None
        if view.obligation_from is None
        else view.obligation_from.isoformat(),
        "partial": view.partial,
        "disclaimer": view.disclaimer,
    }
