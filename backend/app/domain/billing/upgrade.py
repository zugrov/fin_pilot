from decimal import Decimal

from app.domain.billing.pricing import MIN_CHARGE, additional_full_period
from app.domain.money import money


def prorate(
    full_unit: Decimal,
    slots: int,
    remaining_seconds: int,
    period_seconds: int,
) -> Decimal:
    if slots < 1:
        raise ValueError("нужен хотя бы один слот")
    if period_seconds <= 0 or remaining_seconds < 0 or remaining_seconds > period_seconds:
        raise ValueError("некорректный остаток периода")
    raw = full_unit * slots * Decimal(remaining_seconds) / Decimal(period_seconds)
    return money(raw)


def upgrade_amount(
    *,
    interval: str,
    added_slots: int,
    remaining_seconds: int,
    period_seconds: int,
    discount_percent: Decimal,
) -> Decimal | None:
    """None означает отложить до следующего периода: сумма меньше 1 RUB."""
    unit = additional_full_period(interval, discount_percent)
    amount = prorate(unit, added_slots, remaining_seconds, period_seconds)
    if amount < MIN_CHARGE:
        return None
    return amount
