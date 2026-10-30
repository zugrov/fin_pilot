from datetime import date
from decimal import Decimal

from app.domain.imports.fa_r03.clientbank_daily import ClientBankDailySection
from app.domain.imports.fa_r03.osv_month import (
    OsvCounterpartyLine,
    OsvCounterpartySheet,
    OsvDailyLine,
    OsvSingleAccountSheet,
    carry_forward_breaks,
    closing_balance_sides,
    counterparty_turnover_consistent,
    daily_mismatch_days,
    s1_days_without_osv_daily,
)


def _section(
    day: str, opening: str, total_in: str, total_out: str, closing: str
) -> ClientBankDailySection:
    d = date.fromisoformat(day)
    return ClientBankDailySection(
        d, d, "51", Decimal(opening), Decimal(total_in), Decimal(total_out), Decimal(closing)
    )


def test_daily_mismatch_detects_turnover_delta() -> None:
    osv = (
        OsvDailyLine(
            date(2026, 8, 1),
            Decimal("100.00"),
            Decimal("10.00"),
            Decimal("5.00"),
            Decimal("105.00"),
        ),
    )
    sections = [_section("2026-08-01", "100.00", "11.00", "5.00", "106.00")]
    assert daily_mismatch_days(osv, sections) == [date(2026, 8, 1)]


def test_s1_days_without_osv_daily() -> None:
    osv = (
        OsvDailyLine(
            date(2026, 8, 1), Decimal("0.00"), Decimal("0.00"), Decimal("0.00"), Decimal("0.00")
        ),
    )
    sections = [
        _section("2026-08-01", "0.00", "0.00", "0.00", "0.00"),
        _section("2026-08-02", "0.00", "0.00", "0.00", "0.00"),
    ]
    assert s1_days_without_osv_daily(osv, sections) == [date(2026, 8, 2)]


def test_counterparty_turnover_sums() -> None:
    rows = (
        OsvCounterpartyLine(
            "A",
            Decimal("0"),
            Decimal("0"),
            Decimal("100.00"),
            Decimal("40.00"),
            Decimal("60.00"),
            Decimal("0"),
        ),
        OsvCounterpartyLine(
            "B",
            Decimal("0"),
            Decimal("0"),
            Decimal("50.00"),
            Decimal("10.00"),
            Decimal("40.00"),
            Decimal("0"),
        ),
    )
    sheet = OsvCounterpartySheet(
        "62", Decimal("0"), Decimal("150.00"), Decimal("50.00"), Decimal("100.00"), rows
    )
    assert counterparty_turnover_consistent(sheet)


def test_closing_balance_sides_and_carry_forward() -> None:
    prev_rows = (
        OsvCounterpartyLine(
            "A",
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("100.00"),
            Decimal("0"),
        ),
        OsvCounterpartyLine(
            "B",
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("50.00"),
        ),
    )
    cur_rows = (
        OsvCounterpartyLine(
            "A",
            Decimal("100.00"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("100.00"),
            Decimal("0"),
        ),
        OsvCounterpartyLine(
            "B",
            Decimal("0"),
            Decimal("50.00"),
            Decimal("0"),
            Decimal("0"),
            Decimal("0"),
            Decimal("50.00"),
        ),
    )
    prev = OsvCounterpartySheet(
        "62", Decimal("50.00"), Decimal("0"), Decimal("0"), Decimal("50.00"), prev_rows
    )
    cur = OsvCounterpartySheet(
        "62", Decimal("50.00"), Decimal("0"), Decimal("0"), Decimal("50.00"), cur_rows
    )
    debit, credit = closing_balance_sides(prev)
    assert debit == Decimal("100.00")
    assert credit == Decimal("-50.00")
    assert carry_forward_breaks(prev, cur) == 0


def test_osv_single_account_sheet_totals() -> None:
    sheet = OsvSingleAccountSheet(
        "51",
        Decimal("10.00"),
        Decimal("100.00"),
        Decimal("40.00"),
        Decimal("70.00"),
        (
            OsvDailyLine(
                date(2026, 8, 1),
                Decimal("10.00"),
                Decimal("100.00"),
                Decimal("40.00"),
                Decimal("70.00"),
            ),
        ),
    )
    sections = [_section("2026-08-01", "10.00", "100.00", "40.00", "70.00")]
    assert daily_mismatch_days(sheet.daily, sections) == []
