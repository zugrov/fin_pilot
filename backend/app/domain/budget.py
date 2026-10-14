import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.domain.money import money

CASH_METRICS = frozenset({"cash_in", "cash_out"})
REVENUE_METRICS = frozenset({"revenue"})


@dataclass(frozen=True)
class Deviation:
    plan_to_date: Decimal
    fact: Decimal
    delta: Decimal
    percent: Decimal | None
    status: str
    character: str


def metrics_for(basis: str) -> frozenset[str]:
    if basis == "cash":
        return CASH_METRICS
    if basis == "revenue":
        return REVENUE_METRICS
    return frozenset()


def allocate_month(year: int, month: int, amount: Decimal) -> list[tuple[date, Decimal]]:
    """Равные доли по календарным дням. Остаток копеек остаётся на последнем дне."""
    days = calendar.monthrange(year, month)[1]
    cents = int((money(amount) * 100).to_integral_value(rounding=ROUND_HALF_UP))
    base, leftover = divmod(cents, days)
    shares: list[tuple[date, Decimal]] = []
    for day in range(1, days + 1):
        piece = base + (leftover if day == days else 0)
        shares.append((date(year, month, day), Decimal(piece) / Decimal(100)))
    return shares


def compare(metric: str, plan: Decimal, fact: Decimal, section: str | None) -> Deviation:
    plan = money(plan)
    fact = money(fact)
    if plan == 0 and fact == 0:
        return Deviation(plan, fact, Decimal("0.00"), Decimal("0.00"), "совпадает", "neutral")
    if plan == 0:
        character = "adverse" if metric == "cash_out" and fact > 0 else "neutral"
        return Deviation(plan, fact, money(fact - plan), None, "вне бюджета", character)
    delta = money(fact - plan)
    percent = money(delta / abs(plan) * Decimal(100))
    if delta == 0:
        return Deviation(plan, fact, delta, percent, "совпадает", "neutral")
    character = _character(metric, delta, section)
    return Deviation(plan, fact, delta, percent, "отклонение", character)


def _character(metric: str, delta: Decimal, section: str | None) -> str:
    if metric == "cash_out" and delta > 0:
        return "adverse"
    if metric == "revenue" and delta < 0:
        return "adverse"
    # Превышение поступления займа само по себе благоприятным не считается.
    if metric == "cash_in" and section == "financing" and delta > 0:
        return "neutral"
    return "neutral"
