import calendar
from datetime import datetime
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")


def add_calendar_months(
    start: datetime,
    months: int,
    anchor_day: int,
    tz: ZoneInfo,
) -> datetime:
    """Сдвигает границу на календарные месяцы, сохраняя день якоря.

    Если дня нет, берётся последний день месяца. Следующий шаг снова смотрит
    на исходный якорь, поэтому 31-е и 29 февраля не «съезжают» навсегда.
    """
    if start.tzinfo is None:
        raise ValueError("нужна временная зона")
    local = start.astimezone(tz)
    index = local.month - 1 + months
    year = local.year + index // 12
    month = index % 12 + 1
    day = min(anchor_day, calendar.monthrange(year, month)[1])
    shifted = datetime(
        year,
        month,
        day,
        local.hour,
        local.minute,
        local.second,
        local.microsecond,
        tzinfo=tz,
    )
    return shifted.astimezone(start.tzinfo)


def period_end(start: datetime, interval: str, anchor_day: int, tz: ZoneInfo) -> datetime:
    if interval == "month":
        months = 1
    elif interval == "year":
        months = 12
    else:
        raise ValueError("неизвестный интервал")
    return add_calendar_months(start, months, anchor_day, tz)


def renewal_bounds(
    *,
    paid_through: datetime | None,
    billing_anchor: datetime | None,
    succeeded_at: datetime,
    interval: str,
    tz: ZoneInfo,
) -> tuple[datetime, datetime, datetime]:
    """Начало, конец и якорь следующего периода.

    Раннее продление стартует в текущий конец и не укорачивает оплаченное.
    Первая и поздняя оплата стартуют в подтверждённый succeeded_at.
    """
    if paid_through is not None and succeeded_at < paid_through:
        start = paid_through
        anchor = billing_anchor or paid_through
    else:
        start = succeeded_at
        anchor = succeeded_at
    anchor_day = anchor.astimezone(tz).day
    end = period_end(start, interval, anchor_day, tz)
    return start, end, anchor
