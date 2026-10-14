from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app.domain.billing.periods import MOSCOW
from app.domain.money import money

DEFAULT_COOLDOWN = 360


def median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    count = len(ordered)
    mid = count // 2
    if count % 2 == 1:
        return ordered[mid]
    return money((ordered[mid - 1] + ordered[mid]) / Decimal(2))


def expense_hit(delta: Decimal, percent: Decimal | None, amount: Decimal, rate: Decimal) -> bool:
    if percent is None or delta < amount:
        return False
    return percent >= rate


def revenue_hit(delta: Decimal, percent: Decimal | None, amount: Decimal, rate: Decimal) -> bool:
    if percent is None or delta >= 0:
        return False
    shortfall = money(-delta)
    return shortfall >= amount and percent <= rate


def share_above(part: Decimal, whole: Decimal, limit: Decimal) -> Decimal | None:
    if whole == 0:
        return None
    percent = money(part / whole * Decimal(100))
    if percent > limit:
        return percent
    return None


def matched_horizon(days: int, horizons: list[int]) -> int | None:
    later = [item for item in horizons if item >= days]
    if not later:
        return None
    return min(later)


def coverage_is_stale(coverage: date | None, at: datetime, lag_hours: int) -> bool | None:
    """Пустое покрытие — не устаревание. Выходные в лаг не входят."""
    if coverage is None:
        return None
    local = at.astimezone(MOSCOW)
    start = datetime.combine(coverage + timedelta(days=1), time.min, tzinfo=MOSCOW)
    limit = lag_hours * 60
    return _business_minutes(start, local, limit) > limit


def _business_minutes(start: datetime, end: datetime, limit: int) -> int:
    if end <= start:
        return 0
    counted = 0
    cursor = start
    while cursor < end:
        if cursor.weekday() >= 5:
            skip = 7 - cursor.weekday()
            cursor = datetime.combine(
                cursor.date() + timedelta(days=skip), time.min, tzinfo=cursor.tzinfo
            )
            continue
        next_day = datetime.combine(
            cursor.date() + timedelta(days=1), time.min, tzinfo=cursor.tzinfo
        )
        chunk_end = end if end < next_day else next_day
        delta = chunk_end - cursor
        counted += delta.days * 24 * 60 + delta.seconds // 60
        if counted > limit:
            return counted
        cursor = chunk_end
    return counted
