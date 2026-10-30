"""Проверки полной ОСВ (S3): итоги, первый уровень, переход месяца."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import xlrd  # type: ignore[import-untyped]

from app.domain.imports.fa_r03.xls_reader import (
    OsvRow,
    OsvSheet,
    XlsFormatError,
    cell_amount,
    read_osv,
)
from app.domain.money import money

ZERO = Decimal("0.00")
TOTAL_LABEL = "Итого"


@dataclass(frozen=True)
class OsvColumnTotals:
    opening_debit: Decimal
    opening_credit: Decimal
    turnover_debit: Decimal
    turnover_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal

    def balanced_opening(self) -> bool:
        return money(self.opening_debit) == money(self.opening_credit)

    def balanced_turnover(self) -> bool:
        return money(self.turnover_debit) == money(self.turnover_credit)

    def balanced_closing(self) -> bool:
        return money(self.closing_debit) == money(self.closing_credit)


def net_balance(row: OsvRow) -> Decimal:
    return money(row.closing_debit - row.closing_credit)


def net_opening(row: OsvRow) -> Decimal:
    return money(row.opening_debit - row.opening_credit)


def read_osv_grand_total(path: Path) -> OsvColumnTotals:
    """Строка «Итого» полной ОСВ."""
    try:
        book = xlrd.open_workbook(str(path), formatting_info=True)
    except Exception as exc:  # noqa: BLE001
        raise XlsFormatError(f"не удалось открыть {path.name}: {exc}") from exc
    sheet = book.sheet_by_index(0)
    for row in range(sheet.nrows - 1, -1, -1):
        label = str(sheet.cell_value(row, 0)).strip()
        if label == TOTAL_LABEL or label.startswith("Итого"):
            return OsvColumnTotals(
                opening_debit=cell_amount(sheet.cell_value(row, 1)),
                opening_credit=cell_amount(sheet.cell_value(row, 2)),
                turnover_debit=cell_amount(sheet.cell_value(row, 3)),
                turnover_credit=cell_amount(sheet.cell_value(row, 4)),
                closing_debit=cell_amount(sheet.cell_value(row, 5)),
                closing_credit=cell_amount(sheet.cell_value(row, 6)),
            )
    raise XlsFormatError("в ОСВ нет строки «Итого»")


def first_level_totals(sheet: OsvSheet) -> OsvColumnTotals:
    """Сумма счетов первого уровня (код без точки)."""
    rows = [row for row in sheet.rows if row.level == 1]
    return OsvColumnTotals(
        opening_debit=money(sum((row.opening_debit for row in rows), ZERO)),
        opening_credit=money(sum((row.opening_credit for row in rows), ZERO)),
        turnover_debit=money(sum((row.turnover_debit for row in rows), ZERO)),
        turnover_credit=money(sum((row.turnover_credit for row in rows), ZERO)),
        closing_debit=money(sum((row.closing_debit for row in rows), ZERO)),
        closing_credit=money(sum((row.closing_credit for row in rows), ZERO)),
    )


def totals_equal(first: OsvColumnTotals, second: OsvColumnTotals) -> bool:
    keys = (
        "opening_debit",
        "opening_credit",
        "turnover_debit",
        "turnover_credit",
        "closing_debit",
        "closing_credit",
    )
    return all(money(getattr(first, key)) == money(getattr(second, key)) for key in keys)


def month_carry_breaks(previous: OsvSheet, current: OsvSheet) -> int:
    """Число счетов, у которых конец прошлого месяца ≠ начало текущего."""
    breaks = 0
    for row in previous.rows:
        nxt = current.by_code(row.code)
        if nxt is None:
            continue
        closing_net = money(row.closing_debit - row.closing_credit)
        opening_net = money(nxt.opening_debit - nxt.opening_credit)
        if closing_net != opening_net:
            breaks += 1
    return breaks


def load_osv_sheet(path: Path) -> OsvSheet:
    return read_osv(path)
