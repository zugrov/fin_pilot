from datetime import date
from decimal import Decimal

from app.domain.forecast import PlanSlice, project
from app.domain.imports.plan_reader import read_plan_csv
from app.domain.recurrence import occurrence_dates


def _event(direction: str, amount: str, day: date, confidence: str = "expected") -> PlanSlice:
    return PlanSlice("e", direction, Decimal(amount), day, day, confidence)


def test_f1_gap_is_the_shortfall() -> None:
    as_of = date(2026, 10, 14)
    tomorrow = date(2026, 10, 15)
    view = project(
        Decimal("100000.00"),
        as_of,
        (
            _event("in", "20000.00", tomorrow),
            _event("out", "150000.00", tomorrow),
        ),
        "base",
    )
    point = view.points[1]
    assert point.closing == Decimal("-30000.00")
    assert view.gap_date == tomorrow
    assert view.gap_amount == Decimal("30000.00")
    assert "рисков нет" not in str(view)


def test_conservative_haircut_keeps_confirmed() -> None:
    as_of = date(2026, 10, 1)
    day = date(2026, 10, 2)
    view = project(
        Decimal("0.00"),
        as_of,
        (
            PlanSlice("exp", "in", Decimal("100000.00"), day, day, "expected"),
            PlanSlice("con", "in", Decimal("50000.00"), day, day, "confirmed"),
        ),
        "conservative",
    )
    amounts = {item.event_id: (item.day, item.amount) for item in view.flows}
    assert amounts["exp"] == (date(2026, 10, 9), Decimal("80000.00"))
    assert amounts["con"] == (day, Decimal("50000.00"))


def test_february_31_is_the_last_day_once() -> None:
    dates = occurrence_dates(
        frequency="monthly",
        interval_count=1,
        day_of_month=31,
        start_date=date(2026, 1, 31),
        end_date=None,
        as_of=date(2026, 2, 1),
        horizon_end=date(2026, 4, 1),
    )
    assert dates.count(date(2026, 2, 28)) == 1
    assert all(item.month != 2 or item.day == 28 for item in dates)


def test_plan_header_is_rejected() -> None:
    try:
        read_plan_csv(b"external_id,amount\n1,10\n", encoding="utf-8", max_rows=10)
    except Exception as exc:
        assert exc.code == "unsupported_format"
    else:
        raise AssertionError("header accepted")
