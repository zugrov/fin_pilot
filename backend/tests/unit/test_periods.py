from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.domain.billing.periods import (
    MOSCOW,
    add_calendar_months,
    period_end,
    renewal_bounds,
)

UTC = ZoneInfo("UTC")


def _msk(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, 0, tzinfo=MOSCOW)


def test_pay20_month_ends_keep_anchor_day() -> None:
    anchor = _msk(2024, 1, 31)
    feb = add_calendar_months(anchor, 1, 31, MOSCOW)
    march = add_calendar_months(feb, 1, 31, MOSCOW)
    april = add_calendar_months(march, 1, 31, MOSCOW)
    assert feb.astimezone(MOSCOW) == _msk(2024, 2, 29)
    assert march.astimezone(MOSCOW) == _msk(2024, 3, 31)
    assert april.astimezone(MOSCOW) == _msk(2024, 4, 30)
    may = add_calendar_months(april, 1, 31, MOSCOW)
    assert may.astimezone(MOSCOW) == _msk(2024, 5, 31)


def test_pay20_non_leap_february() -> None:
    anchor = _msk(2025, 1, 31)
    feb = add_calendar_months(anchor, 1, 31, MOSCOW)
    march = add_calendar_months(feb, 1, 31, MOSCOW)
    assert feb.astimezone(MOSCOW) == _msk(2025, 2, 28)
    assert march.astimezone(MOSCOW) == _msk(2025, 3, 31)


def test_year7_leap_anchor_does_not_drift() -> None:
    anchor = _msk(2024, 2, 29)
    plus_12 = add_calendar_months(anchor, 12, 29, MOSCOW)
    plus_48 = add_calendar_months(anchor, 48, 29, MOSCOW)
    assert plus_12.astimezone(MOSCOW) == _msk(2025, 2, 28)
    assert plus_48.astimezone(MOSCOW) == _msk(2028, 2, 29)


def test_year7_annual_period_is_twelve_calendar_months() -> None:
    start = _msk(2024, 2, 29, 8)
    end = period_end(start, "year", 29, MOSCOW)
    assert end.astimezone(MOSCOW) == _msk(2025, 2, 28, 8)


def test_pay8_early_renewal_starts_at_current_end() -> None:
    anchor = _msk(2026, 3, 15, 10)
    current_end = period_end(anchor, "month", 15, MOSCOW)
    early = current_end - timedelta(days=5)
    start, end, kept = renewal_bounds(
        paid_through=current_end,
        billing_anchor=anchor,
        succeeded_at=early,
        interval="month",
        tz=MOSCOW,
    )
    assert start == current_end
    assert kept == anchor
    assert end == period_end(current_end, "month", 15, MOSCOW)
    assert start < end


def test_late_renewal_starts_at_succeeded_at() -> None:
    anchor = _msk(2026, 1, 31, 9)
    paid_through = period_end(anchor, "month", 31, MOSCOW)
    late = _msk(2026, 4, 2, 11)
    start, end, kept = renewal_bounds(
        paid_through=paid_through,
        billing_anchor=anchor,
        succeeded_at=late,
        interval="month",
        tz=MOSCOW,
    )
    assert start == late
    assert kept == late
    assert end.astimezone(MOSCOW).day == 2


def test_upgrade_discount_snapshot_not_global() -> None:
    from app.domain.billing.upgrade import upgrade_amount

    paid = upgrade_amount(
        interval="year",
        added_slots=1,
        remaining_seconds=50,
        period_seconds=100,
        discount_percent=Decimal("15.00"),
    )
    changed_global = upgrade_amount(
        interval="year",
        added_slots=1,
        remaining_seconds=50,
        period_seconds=100,
        discount_percent=Decimal("0.00"),
    )
    assert paid == Decimal("7650.00")
    assert changed_global == Decimal("9000.00")
