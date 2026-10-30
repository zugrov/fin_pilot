from decimal import Decimal

from app.domain.imports.fa_r03.osv_s3 import (
    OsvColumnTotals,
    first_level_totals,
    month_carry_breaks,
    totals_equal,
)
from app.domain.imports.fa_r03.xls_reader import OsvRow, OsvSheet


def _row(code: str, level: int, **amounts: str) -> OsvRow:
    return OsvRow(
        code=code,
        level=level,
        opening_debit=Decimal(amounts.get("od", "0")),
        opening_credit=Decimal(amounts.get("oc", "0")),
        turnover_debit=Decimal(amounts.get("td", "0")),
        turnover_credit=Decimal(amounts.get("tc", "0")),
        closing_debit=Decimal(amounts.get("cd", "0")),
        closing_credit=Decimal(amounts.get("cc", "0")),
    )


def test_first_level_totals_and_equality() -> None:
    sheet = OsvSheet(
        rows=(
            _row("01", 1, od="10", oc="10", td="100", tc="100", cd="10", cc="10"),
            _row("01.01", 2, od="10", td="100", cd="10"),
            _row("02", 1, od="5", oc="5", td="50", tc="50", cd="5", cc="5"),
        )
    )
    level1 = first_level_totals(sheet)
    grand = OsvColumnTotals(
        opening_debit=Decimal("15"),
        opening_credit=Decimal("15"),
        turnover_debit=Decimal("150"),
        turnover_credit=Decimal("150"),
        closing_debit=Decimal("15"),
        closing_credit=Decimal("15"),
    )
    assert totals_equal(level1, grand)


def test_month_carry_breaks() -> None:
    prev = OsvSheet(
        rows=(
            _row("51", 1, od="100", cd="100"),
            _row("62", 1, od="50", cd="60"),
        )
    )
    cur = OsvSheet(
        rows=(
            _row("51", 1, od="100", cd="100"),
            _row("62", 1, od="55", cd="60"),
        )
    )
    assert month_carry_breaks(prev, cur) == 1
