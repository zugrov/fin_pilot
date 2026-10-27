"""Независимый ORACLE дебиторки FA-R06.1-P2 (as_of=2026-10-31, gross inc VAT)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

AS_OF = date(2026, 10, 31)

CP1_INN = "7700000901"
CP2_INN = "7700000902"


@dataclass(frozen=True)
class ReceivableOracleRow:
    doc_id: str
    recognition_date: date
    counterparty_inn: str | None
    gross_inc_vat: Decimal
    return_inc_vat: Decimal
    matched: Decimal
    include_in_aging_report: bool = True

    @property
    def balance(self) -> Decimal:
        return self.gross_inc_vat - self.return_inc_vat - self.matched

    @property
    def age_days(self) -> int:
        return (AS_OF - self.recognition_date).days

    @property
    def bucket(self) -> str:
        age = self.age_days
        if age <= 30:
            return "0-30"
        if age <= 60:
            return "31-60"
        if age <= 90:
            return "61-90"
        return ">90"


UNALLOCATED_CASH_RECEIPTS = (
    {
        "label": "неразнесённые поступления",
        "cash_external_id": "rd-c-adv",
        "amount": Decimal("15000.00"),
        "note": "сценарий D: аванс не уменьшает entry rd-r-d",
    },
)

RECEIVABLE_DEMO_ROWS: tuple[ReceivableOracleRow, ...] = (
    ReceivableOracleRow("rd-r-a", date(2026, 10, 5), CP1_INN, Decimal("12000.00"), Decimal("0"), Decimal("0")),
    ReceivableOracleRow("rd-r-b", date(2026, 10, 10), CP1_INN, Decimal("10000.00"), Decimal("0"), Decimal("4000.00")),
    ReceivableOracleRow(
        "rd-r-c-sale",
        date(2026, 10, 12),
        CP1_INN,
        Decimal("8000.00"),
        Decimal("0"),
        Decimal("0"),
    ),
    ReceivableOracleRow(
        "rd-r-c-ret",
        date(2026, 10, 14),
        CP1_INN,
        Decimal("0"),
        Decimal("2000.00"),
        Decimal("0"),
    ),
    ReceivableOracleRow("rd-r-d", date(2026, 10, 20), CP2_INN, Decimal("6000.00"), Decimal("0"), Decimal("0")),
    ReceivableOracleRow("rd-r-e", date(2026, 10, 25), None, Decimal("1500.00"), Decimal("0"), Decimal("0")),
    ReceivableOracleRow("rd-r-f1", date(2026, 9, 20), CP2_INN, Decimal("5000.00"), Decimal("0"), Decimal("0")),
    ReceivableOracleRow("rd-r-f2", date(2026, 8, 25), CP2_INN, Decimal("5000.00"), Decimal("0"), Decimal("0")),
    ReceivableOracleRow("rd-r-f3", date(2026, 5, 15), CP2_INN, Decimal("5000.00"), Decimal("0"), Decimal("0")),
    ReceivableOracleRow("rd-r-b30", date(2026, 10, 1), CP2_INN, Decimal("1.00"), Decimal("0"), Decimal("0")),
    ReceivableOracleRow("rd-r-b31", date(2026, 9, 30), CP2_INN, Decimal("1.00"), Decimal("0"), Decimal("0")),
    ReceivableOracleRow("rd-r-b60", date(2026, 9, 1), CP2_INN, Decimal("1.00"), Decimal("0"), Decimal("0")),
    ReceivableOracleRow("rd-r-b61", date(2026, 8, 31), CP2_INN, Decimal("1.00"), Decimal("0"), Decimal("0")),
    ReceivableOracleRow("rd-r-b90", date(2026, 8, 2), CP2_INN, Decimal("1.00"), Decimal("0"), Decimal("0")),
    ReceivableOracleRow("rd-r-b91", date(2026, 8, 1), CP2_INN, Decimal("1.00"), Decimal("0"), Decimal("0")),
    ReceivableOracleRow(
        "rd-r-paid",
        date(2026, 10, 28),
        CP1_INN,
        Decimal("10000.00"),
        Decimal("0"),
        Decimal("10000.00"),
        include_in_aging_report=False,
    ),
    # Строка для негативного теста match>gross (rd-r-over); balance=1000 входит в итоги ORACLE §6.3.
    ReceivableOracleRow("rd-r-over", date(2026, 10, 30), CP1_INN, Decimal("1000.00"), Decimal("0"), Decimal("0")),
)

def matches_plus_return_exceed_gross(
    gross_inc_vat: Decimal, return_inc_vat: Decimal, matched: Decimal
) -> bool:
    """Одна логическая продажа: сумма связей + возврат не должна превышать gross."""
    return matched + return_inc_vat > gross_inc_vat


def rd_c_logical_line() -> tuple[Decimal, Decimal]:
    """Документ RD-C: sale rd-r-c-sale + return rd-r-c-ret."""
    sale = next(row for row in RECEIVABLE_DEMO_ROWS if row.doc_id == "rd-r-c-sale")
    ret = next(row for row in RECEIVABLE_DEMO_ROWS if row.doc_id == "rd-r-c-ret")
    return sale.gross_inc_vat, ret.return_inc_vat


MATCH_PLAN: tuple[tuple[str, str, str], ...] = (
    ("rd-r-b", "rd-c-b", "4000.00"),
    ("rd-r-paid", "rd-c-paid", "10000.00"),
)


def aging_report_rows() -> tuple[ReceivableOracleRow, ...]:
    return tuple(row for row in RECEIVABLE_DEMO_ROWS if row.include_in_aging_report and row.balance != 0)


def total_balance() -> Decimal:
    return sum((row.balance for row in aging_report_rows()), Decimal("0"))


def totals_by_bucket() -> dict[str, Decimal]:
    totals = {"0-30": Decimal("0"), "31-60": Decimal("0"), "61-90": Decimal("0"), ">90": Decimal("0")}
    for row in aging_report_rows():
        totals[row.bucket] += row.balance
    return totals


def totals_by_counterparty() -> dict[str | None, Decimal]:
    totals: dict[str | None, Decimal] = {}
    for row in aging_report_rows():
        totals[row.counterparty_inn] = totals.get(row.counterparty_inn, Decimal("0")) + row.balance
    return totals
