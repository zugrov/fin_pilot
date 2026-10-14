import calendar
from datetime import date, timedelta


def occurrence_dates(
    *,
    frequency: str,
    interval_count: int,
    day_of_month: int | None,
    start_date: date,
    end_date: date | None,
    as_of: date,
    horizon_end: date,
) -> tuple[date, ...]:
    limit = horizon_end if end_date is None else min(end_date, horizon_end)
    if frequency == "weekly":
        return _weekly(start_date, interval_count, as_of, limit)
    if frequency == "monthly" and day_of_month is not None:
        return _monthly(start_date, interval_count, day_of_month, as_of, limit)
    return ()


def _weekly(start: date, interval_count: int, as_of: date, limit: date) -> tuple[date, ...]:
    step = timedelta(days=7 * interval_count)
    cursor = start
    while cursor < as_of:
        cursor += step
    found: list[date] = []
    while cursor <= limit and len(found) < 16:
        found.append(cursor)
        cursor += step
    return tuple(found)


def _monthly(
    start: date, interval_count: int, day_of_month: int, as_of: date, limit: date
) -> tuple[date, ...]:
    year, month = start.year, start.month
    found: list[date] = []
    for _ in range(36):
        occurred = _clamped(year, month, day_of_month)
        if occurred > limit:
            break
        if occurred >= start and occurred >= as_of:
            found.append(occurred)
        if len(found) >= 8:
            break
        year, month = _add_months(year, month, interval_count)
    return tuple(found)


def _clamped(year: int, month: int, day_of_month: int) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day_of_month, last))


def _add_months(year: int, month: int, step: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + step
    return index // 12, index % 12 + 1
