from datetime import date, datetime
from decimal import Decimal

import pytest
from app.domain.alerts import coverage_is_stale, expense_hit, median
from app.domain.billing.periods import MOSCOW
from app.domain.budget import allocate_month, compare
from app.domain.imports.budget_reader import read_budget_csv
from app.domain.imports.contracts import ImportFormatError


def test_b3_daily_allocations_sum_to_the_month() -> None:
    shares = allocate_month(2026, 10, Decimal("100.00"))
    assert len(shares) == 31
    assert sum(amount for _day, amount in shares) == Decimal("100.00")
    assert shares[-1][1] >= shares[0][1]


def test_b2_zero_plan_is_outside_budget() -> None:
    view = compare("cash_out", Decimal("0.00"), Decimal("10000.00"), None)
    assert view.percent is None
    assert view.status == "вне бюджета"
    both = compare("cash_out", Decimal("0.00"), Decimal("0.00"), None)
    assert both.percent == Decimal("0.00")


def test_b1_threshold_is_separate_from_the_deviation() -> None:
    view = compare("cash_out", Decimal("100000.00"), Decimal("120000.00"), None)
    assert view.delta == Decimal("20000.00")
    assert view.percent == Decimal("20.00")
    assert view.character == "adverse"
    assert expense_hit(view.delta, view.percent, Decimal("50000.00"), Decimal("15.00")) is False


def test_loan_excess_is_not_adverse() -> None:
    view = compare("cash_in", Decimal("1000.00"), Decimal("5000.00"), "financing")
    assert view.character == "neutral"


def test_weekend_does_not_count_as_source_lag() -> None:
    friday = date(2026, 10, 16)
    monday = datetime(2026, 10, 19, 10, 0, tzinfo=MOSCOW)
    tuesday = datetime(2026, 10, 20, 1, 0, tzinfo=MOSCOW)
    assert coverage_is_stale(friday, monday, 24) is False
    assert coverage_is_stale(friday, tuesday, 24) is True
    assert coverage_is_stale(None, tuesday, 24) is None


def test_median_excludes_nothing_extra() -> None:
    assert median([Decimal("10000.00")] * 10) == Decimal("10000.00")


def test_unknown_budget_header_is_rejected() -> None:
    with pytest.raises(ImportFormatError) as caught:
        read_budget_csv(b"external_id,amount\n1,10\n", encoding="utf-8", max_rows=10)
    assert caught.value.code == "unsupported_format"
