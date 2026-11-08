from datetime import date
from decimal import Decimal

from app.domain.usn_vat_threshold import assess_usn_vat_threshold


def _sale(day: str, amount: str) -> tuple[date, str, Decimal]:
    return (date.fromisoformat(day), "sale", Decimal(amount))


def _ret(day: str, amount: str) -> tuple[date, str, Decimal]:
    return (date.fromisoformat(day), "return", Decimal(amount))


def test_ok_below_80_percent() -> None:
    rows = (_sale("2026-10-10", "1000000.00"),)
    view = assess_usn_vat_threshold(
        rows,
        as_of=date(2026, 10, 31),
        threshold=Decimal("20000000.00"),
        partial=False,
    )
    assert view.status == "ok"
    assert view.percent == Decimal("5.00")
    assert view.exceeded_month is None


def test_approaching_at_80_percent() -> None:
    rows = (_sale("2026-10-01", "16000000.00"),)
    view = assess_usn_vat_threshold(
        rows,
        as_of=date(2026, 10, 31),
        threshold=Decimal("20000000.00"),
        partial=False,
    )
    assert view.status == "approaching"
    assert view.ytd_revenue == Decimal("16000000.00")


def test_exceeded_and_obligation_month() -> None:
    rows = (
        _sale("2026-09-15", "15000000.00"),
        _sale("2026-10-05", "6000000.00"),
    )
    view = assess_usn_vat_threshold(
        rows,
        as_of=date(2026, 10, 31),
        threshold=Decimal("20000000.00"),
        partial=False,
    )
    assert view.status == "exceeded"
    assert view.exceeded_month == date(2026, 10, 1)
    assert view.obligation_from == date(2026, 11, 1)


def test_exceeded_month_first_crossing() -> None:
    rows = (
        _sale("2026-08-01", "19000000.00"),
        _sale("2026-09-01", "2000000.00"),
    )
    view = assess_usn_vat_threshold(
        rows,
        as_of=date(2026, 9, 30),
        threshold=Decimal("20000000.00"),
        partial=False,
    )
    assert view.exceeded_month == date(2026, 9, 1)


def test_year_transition_ignores_prior_year() -> None:
    rows = (
        _sale("2025-12-20", "50000000.00"),
        _sale("2026-01-10", "1000.00"),
    )
    view = assess_usn_vat_threshold(
        rows,
        as_of=date(2026, 1, 31),
        threshold=Decimal("20000000.00"),
        partial=False,
    )
    assert view.ytd_revenue == Decimal("1000.00")
    assert view.status == "ok"


def test_return_reduces_ytd() -> None:
    rows = (_sale("2026-10-01", "17000000.00"), _ret("2026-10-15", "1000000.00"))
    view = assess_usn_vat_threshold(
        rows,
        as_of=date(2026, 10, 31),
        threshold=Decimal("20000000.00"),
        partial=False,
    )
    assert view.ytd_revenue == Decimal("16000000.00")
    assert view.status == "approaching"


def test_partial_flag_preserved() -> None:
    view = assess_usn_vat_threshold(
        (),
        as_of=date(2026, 6, 1),
        threshold=Decimal("1"),
        partial=True,
    )
    assert view.partial is True
