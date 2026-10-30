"""Сверка ОСВ 51/62 с суточными секциями ClientBank (Decimal, допуск 0,00)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.domain.imports.fa_r03.clientbank_daily import ClientBankDailySection
from app.domain.money import money

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class OsvDailyLine:
    day: date
    opening: Decimal
    turnover_in: Decimal
    turnover_out: Decimal
    closing: Decimal


@dataclass(frozen=True)
class OsvSingleAccountSheet:
    account: str
    opening: Decimal
    turnover_in: Decimal
    turnover_out: Decimal
    closing: Decimal
    daily: tuple[OsvDailyLine, ...]


@dataclass(frozen=True)
class OsvCounterpartyLine:
    """Строка ОСВ по контрагенту; name — только для локальной стыковки месяцев."""

    name: str
    opening_debit: Decimal
    opening_credit: Decimal
    turnover_debit: Decimal
    turnover_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal

    @property
    def net_opening(self) -> Decimal:
        return money(self.opening_debit - self.opening_credit)

    @property
    def net_closing(self) -> Decimal:
        return money(self.closing_debit - self.closing_credit)


@dataclass(frozen=True)
class OsvCounterpartySheet:
    account: str
    opening: Decimal
    turnover_in: Decimal
    turnover_out: Decimal
    closing: Decimal
    rows: tuple[OsvCounterpartyLine, ...]


def _net(debit: Decimal, credit: Decimal) -> Decimal:
    return money(debit - credit)


def daily_mismatch_days(
    osv_daily: tuple[OsvDailyLine, ...],
    s1_sections: list[ClientBankDailySection],
    *,
    tolerance: Decimal = ZERO,
) -> list[date]:
    """Дни, где суточная ОСВ не совпала с секцией ClientBank."""
    by_day: dict[date, ClientBankDailySection] = {}
    for section in s1_sections:
        by_day[section.period_start] = section
    bad: list[date] = []
    for line in osv_daily:
        section = by_day.get(line.day)
        if section is None:
            bad.append(line.day)
            continue
        pairs = (
            (line.opening, section.opening),
            (line.turnover_in, section.total_in),
            (line.turnover_out, section.total_out),
            (line.closing, section.closing),
        )
        if any(abs(money(left) - money(right)) > tolerance for left, right in pairs):
            bad.append(line.day)
    return bad


def s1_days_without_osv_daily(
    osv_daily: tuple[OsvDailyLine, ...],
    s1_sections: list[ClientBankDailySection],
) -> list[date]:
    """Секции S1 без строки «Обороты за …» в ОСВ (обычно нулевой день в 1С)."""
    osv_days = {line.day for line in osv_daily}
    missing = [
        section.period_start
        for section in s1_sections
        if section.period_start not in osv_days
    ]
    return sorted(missing)


def osv_totals_mismatch(osv: OsvSingleAccountSheet, s1_totals: tuple[Decimal, ...]) -> bool:
    """Сравнение итога ОСВ с агрегатами S1: opening, in, out, closing."""
    opening, total_in, total_out, closing = s1_totals
    expected = (
        (osv.opening, opening),
        (osv.turnover_in, total_in),
        (osv.turnover_out, total_out),
        (osv.closing, closing),
    )
    return any(abs(money(left) - money(right)) > ZERO for left, right in expected)


def counterparty_turnover_consistent(sheet: OsvCounterpartySheet) -> bool:
    """Сумма оборотов по строкам = оборот счёта."""
    sum_debit = money(sum((row.turnover_debit for row in sheet.rows), ZERO))
    sum_credit = money(sum((row.turnover_credit for row in sheet.rows), ZERO))
    return sum_debit == sheet.turnover_in and sum_credit == sheet.turnover_out


def closing_balance_sides(sheet: OsvCounterpartySheet) -> tuple[Decimal, Decimal]:
    """Сумма дебетовых остатков и сумма кредитовых (авансы, отрицательное число)."""
    debit_total = ZERO
    credit_total = ZERO
    for row in sheet.rows:
        net = row.net_closing
        if net > ZERO:
            debit_total += net
        elif net < ZERO:
            credit_total += net
    return money(debit_total), money(credit_total)


def carry_forward_breaks(
    previous: OsvCounterpartySheet,
    current: OsvCounterpartySheet,
) -> int:
    """Число контрагентов, у которых конец прошлого месяца ≠ начало текущего."""
    prev_by_name = {row.name: row.net_closing for row in previous.rows}
    breaks = 0
    for row in current.rows:
        if row.name not in prev_by_name:
            continue
        if money(prev_by_name[row.name]) != row.net_opening:
            breaks += 1
    return breaks


def carry_forward_union_breaks(
    previous: OsvCounterpartySheet,
    current: OsvCounterpartySheet,
) -> tuple[int, int]:
    """Разрывы перехода и число уникальных контрагентов в объединении двух месяцев."""
    prev_by_name = {row.name: row.net_closing for row in previous.rows}
    names = set(prev_by_name) | {row.name for row in current.rows}
    breaks = 0
    for row in current.rows:
        if row.name not in prev_by_name:
            continue
        if money(prev_by_name[row.name]) != row.net_opening:
            breaks += 1
    return breaks, len(names)
