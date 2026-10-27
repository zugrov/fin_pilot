from datetime import date
from decimal import Decimal

from app.domain.imports.fa_r03.clientbank_daily import ClientBankDailySection
from app.domain.imports.fa_r03.reconcile import (
    Account51Totals,
    Card51Row,
    StatementDocument,
    account51_totals_equal,
    aggregate_card_rows,
    daily_balance_formula_ok,
    daily_chain_errors,
    match_statement_to_card,
)


def _section(
    day: str,
    opening: str,
    total_in: str,
    total_out: str,
    closing: str,
) -> ClientBankDailySection:
    d = date.fromisoformat(day)
    return ClientBankDailySection(
        period_start=d,
        period_end=d,
        account="40702810263310001198",
        opening=Decimal(opening),
        total_in=Decimal(total_in),
        total_out=Decimal(total_out),
        closing=Decimal(closing),
    )


def test_daily_balance_formula_ok_and_fail() -> None:
    ok = _section("2026-09-01", "100", "50", "30", "120")
    assert daily_balance_formula_ok(ok)
    bad = _section("2026-09-02", "100", "50", "30", "119")
    assert not daily_balance_formula_ok(bad)


def test_daily_chain_detects_break() -> None:
    s1 = _section("2026-09-01", "100", "0", "0", "100")
    s2 = _section("2026-09-02", "99", "0", "0", "99")
    errors = daily_chain_errors([s1, s2])
    assert any(item.startswith("chain:") for item in errors)


def test_account51_three_way_zero_tolerance() -> None:
    t = Account51Totals(
        opening=Decimal("1.00"),
        total_in=Decimal("2.00"),
        total_out=Decimal("3.00"),
        closing=Decimal("0.00"),
    )
    assert account51_totals_equal(t, t, t)
    other = Account51Totals(
        opening=Decimal("1.00"),
        total_in=Decimal("2.00"),
        total_out=Decimal("3.00"),
        closing=Decimal("0.01"),
    )
    assert not account51_totals_equal(t, other, other)


def test_aggregate_two_card_rows_one_document() -> None:
    rows = [
        Card51Row("in", date(2026, 9, 4), Decimal("1000.00"), "42"),
        Card51Row("in", date(2026, 9, 4), Decimal("500.00"), "42"),
    ]
    docs = aggregate_card_rows(rows)
    assert len(docs) == 1
    assert docs[0].amount == Decimal("1500.00")
    assert docs[0].source_row_count == 2


def test_match_statement_to_card_with_and_without_doc_number() -> None:
    stmt = StatementDocument("in", date(2026, 9, 5), Decimal("7900.00"), "100")
    card_rows = [
        Card51Row("in", date(2026, 9, 5), Decimal("7900.00"), "100"),
        Card51Row("out", date(2026, 9, 6), Decimal("3000.00"), None),
    ]
    stmt_cash = StatementDocument("out", date(2026, 9, 6), Decimal("3000.00"), "")
    result = match_statement_to_card([stmt, stmt_cash], card_rows)
    assert len(result.matched) == 2
    assert result.unmatched_statement == []
    assert result.unmatched_card == []
    cash_pair = next(pair for pair in result.matched if pair[0].direction == "out")
    assert cash_pair[1].matched_without_doc_number is True
