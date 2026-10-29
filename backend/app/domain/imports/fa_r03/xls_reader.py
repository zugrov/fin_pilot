"""FA-R03.2c: тонкое чтение .xls 1С (карточка 51, ОСВ, ОСВ 57.03).

Только преобразование «лист → простые структуры». Никакой бизнес-логики,
никакой записи в БД. Суммы — Decimal(str(v)) не более 2 знаков, иначе ошибка.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import xlrd  # type: ignore[import-untyped]

MAX_DECIMAL_PLACES = 2

SALDO_PREFIX = "Сальдо на "
TURNOVER_PREFIX = "Обороты за "
TOTAL_LABEL = "Итого"

# Карточка счёта 51: раскладка колонок 1С (0-базные индексы).
CARD_BALANCE_COL = 11
CARD_TURNOVER_DEBIT_COL = 4
CARD_TURNOVER_CREDIT_COL = 7
CARD_DEBIT_AMOUNT_COL = 5
CARD_CREDIT_AMOUNT_COL = 8


class XlsFormatError(ValueError):
    """Файл .xls не соответствует ожидаемой структуре 1С."""


@dataclass(frozen=True)
class AmountCell:
    value: Decimal
    negative: bool


@dataclass(frozen=True)
class OsvRow:
    """Строка ОСВ: счёт и его обороты. Иерархия определяется длиной кода."""

    code: str
    level: int
    opening_debit: Decimal
    opening_credit: Decimal
    turnover_debit: Decimal
    turnover_credit: Decimal
    closing_debit: Decimal
    closing_credit: Decimal


@dataclass(frozen=True)
class OsvSheet:
    rows: tuple[OsvRow, ...]

    def by_code(self, code: str) -> OsvRow | None:
        for row in self.rows:
            if row.code == code:
                return row
        return None

    def level(self, code: str) -> int:
        return len(code.split("."))


@dataclass(frozen=True)
class Card51Row:
    """Строка карточки счёта 51: дата, документ, корреспондирующий счёт, сумма."""

    business_date: date
    document: str
    debit_account: str
    credit_account: str
    debit_amount: Decimal
    credit_amount: Decimal
    running_balance: Decimal | None

    @property
    def direction(self) -> str:
        return "in" if self.debit_amount > 0 else "out"

    @property
    def amount(self) -> Decimal:
        return self.debit_amount if self.debit_amount > 0 else self.credit_amount

    @property
    def counter_account(self) -> str:
        """Счёт-корреспондент: при поступлении — кредит, при списании — дебет."""
        return self.credit_account if self.debit_amount > 0 else self.debit_account


@dataclass(frozen=True)
class Card51Sheet:
    opening_balance: Decimal | None
    rows: tuple[Card51Row, ...]
    turnover_debit: Decimal | None
    turnover_credit: Decimal | None
    closing_balance: Decimal | None


@dataclass(frozen=True)
class Osv57Node:
    """Узел ОСВ 57.03: счёт → контрагент → договор → обороты по дням."""

    name: str
    level: str
    turnover_debit: Decimal
    turnover_credit: Decimal
    children: tuple[Osv57Node, ...]
    daily: tuple[tuple[date, Decimal, Decimal], ...] = ()


@dataclass(frozen=True)
class Osv57Sheet:
    root: Osv57Node
    total_debit: Decimal
    total_credit: Decimal

    def daily_turnovers(self) -> dict[date, Decimal]:
        """Сумма оборотов по дням на уровне договоров (без двойного счёта)."""
        totals: dict[date, Decimal] = {}
        for contract in self._contracts():
            for day, debit, _credit in contract.daily:
                totals[day] = totals.get(day, Decimal("0.00")) + debit
        return {day: _money(value) for day, value in totals.items()}

    def _contracts(self) -> list[Osv57Node]:
        found: list[Osv57Node] = []
        for counterparty in self.root.children:
            for contract in counterparty.children:
                if contract.daily:
                    found.append(contract)
        return found


def cell_amount(raw: object) -> Decimal:
    """Сумма из ячейки: Decimal(str(v)), не более 2 знаков, иначе ошибка."""
    if raw is None or raw == "":
        return Decimal("0.00")
    if isinstance(raw, bool):
        raise XlsFormatError("логическое значение вместо суммы")
    text = str(raw).strip().replace("\xa0", "").replace(" ", "").replace(",", ".")
    if text in {"", "-"}:
        return Decimal("0.00")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise XlsFormatError(f"не сумма: {raw!r}") from exc
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -MAX_DECIMAL_PLACES:
        raise XlsFormatError(f"больше 2 знаков после запятой: {raw!r}")
    return _money(value)


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def parse_day_label(raw: str) -> date | None:
    """«Обороты за 01.09.26» → date(2026, 9, 1); иначе None."""
    text = raw.strip()
    if not text.startswith(TURNOVER_PREFIX):
        return None
    tail = text[len(TURNOVER_PREFIX) :].strip()
    for fmt in ("%d.%m.%y", "%d.%m.%Y"):
        try:
            return datetime.strptime(tail, fmt).date()
        except ValueError:
            continue
    return None


def _open_sheet(path: Path) -> xlrd.sheet.Sheet:
    try:
        book = xlrd.open_workbook(str(path), formatting_info=True)
    except Exception as exc:  # noqa: BLE001 - xlrd бросает разные типы
        raise XlsFormatError(f"не удалось открыть {path.name}: {exc}") from exc
    return book.sheet_by_index(0)


def _open_book(path: Path) -> tuple[xlrd.book.Book, xlrd.sheet.Sheet]:
    try:
        book = xlrd.open_workbook(str(path), formatting_info=True)
    except Exception as exc:  # noqa: BLE001 - xlrd бросает разные типы
        raise XlsFormatError(f"не удалось открыть {path.name}: {exc}") from exc
    return book, book.sheet_by_index(0)


def _indent(book: xlrd.book.Book, sheet: xlrd.sheet.Sheet, row: int, col: int = 0) -> int:
    """Уровень отступа ячейки: 1С задаёт иерархию отступами, а не колонками."""
    try:
        xf = book.xf_list[sheet.cell_xf_index(row, col)]
    except (IndexError, KeyError):
        return 0
    return int(getattr(xf.alignment, "indent_level", 0) or 0)


def _text(sheet: xlrd.sheet.Sheet, row: int, col: int) -> str:
    return str(sheet.cell_value(row, col)).strip()


def _header_row(sheet: xlrd.sheet.Sheet, first_cell: str = "Счет") -> int:
    for row in range(min(sheet.nrows, 20)):
        if _text(sheet, row, 0).startswith(first_cell):
            return row
    raise XlsFormatError(f"не найдена строка заголовка {first_cell!r}")


def read_osv(path: Path) -> OsvSheet:
    """ОСВ: счета с иерархией по длине кода (001, 01.01, 01.01.1)."""
    sheet = _open_sheet(path)
    start = _header_row(sheet) + 2
    rows: list[OsvRow] = []
    for row in range(start, sheet.nrows):
        code = _text(sheet, row, 0)
        if not code or code == TOTAL_LABEL or code.startswith("Итого"):
            continue
        if not _looks_like_account(code):
            continue
        rows.append(
            OsvRow(
                code=code,
                level=len(code.split(".")),
                opening_debit=cell_amount(sheet.cell_value(row, 1)),
                opening_credit=cell_amount(sheet.cell_value(row, 2)),
                turnover_debit=cell_amount(sheet.cell_value(row, 3)),
                turnover_credit=cell_amount(sheet.cell_value(row, 4)),
                closing_debit=cell_amount(sheet.cell_value(row, 5)),
                closing_credit=cell_amount(sheet.cell_value(row, 6)),
            )
        )
    if not rows:
        raise XlsFormatError("ОСВ без строк со счетами")
    return OsvSheet(rows=tuple(rows))


def _looks_like_account(code: str) -> bool:
    parts = code.split(".")
    if not parts[0].isdigit():
        return False
    return all(part.isdigit() for part in parts)


def read_osv_5703(path: Path) -> Osv57Sheet:
    """ОСВ по счёту 57.03: Счёт → Контрагент → Договор → обороты по дням.

    Уровень узла берётся из отступа ячейки (1С: 0 — счёт, 1 — контрагент,
    2 — договор, 3 — «Обороты за ДД.ММ.ГГ»).
    """
    book, sheet = _open_book(path)
    header = _header_row(sheet, "Счет")
    counterparties: list[Osv57Node] = []
    total_debit = Decimal("0.00")
    total_credit = Decimal("0.00")

    root_name = "57.03"
    root_debit = Decimal("0.00")
    root_credit = Decimal("0.00")

    cp_name: str | None = None
    cp_debit = Decimal("0.00")
    cp_credit = Decimal("0.00")
    contracts: list[Osv57Node] = []

    contract_name: str | None = None
    contract_debit = Decimal("0.00")
    contract_credit = Decimal("0.00")
    daily: list[tuple[date, Decimal, Decimal]] = []

    def flush_contract() -> None:
        nonlocal contract_name, contract_debit, contract_credit, daily
        if contract_name is None:
            return
        contracts.append(
            Osv57Node(
                name=contract_name,
                level="contract",
                turnover_debit=_money(contract_debit),
                turnover_credit=_money(contract_credit),
                children=(),
                daily=tuple(daily),
            )
        )
        contract_name = None
        contract_debit = Decimal("0.00")
        contract_credit = Decimal("0.00")
        daily = []

    def flush_counterparty() -> None:
        nonlocal cp_name, cp_debit, cp_credit, contracts
        flush_contract()
        if cp_name is None:
            return
        counterparties.append(
            Osv57Node(
                name=cp_name,
                level="counterparty",
                turnover_debit=_money(cp_debit),
                turnover_credit=_money(cp_credit),
                children=tuple(contracts),
            )
        )
        cp_name = None
        cp_debit = Decimal("0.00")
        cp_credit = Decimal("0.00")
        contracts = []

    for row in range(header + 3, sheet.nrows):
        label = _text(sheet, row, 0)
        if not label:
            continue
        debit = cell_amount(sheet.cell_value(row, 3))
        credit = cell_amount(sheet.cell_value(row, 4))
        indent = _indent(book, sheet, row)

        if label == TOTAL_LABEL:
            flush_counterparty()
            total_debit += debit
            total_credit += credit
            continue

        day = parse_day_label(label)
        if day is not None:
            if contract_name is None:
                raise XlsFormatError("обороты по дням без договора")
            daily.append((day, debit, credit))
            contract_debit += debit
            contract_credit += credit
            continue

        if indent == 0 or _looks_like_account(label):
            flush_counterparty()
            root_name = label
            root_debit = debit
            root_credit = credit
            continue

        if indent == 1:
            flush_counterparty()
            cp_name = label
            cp_debit = debit
            cp_credit = credit
            continue

        # indent >= 2: договор
        flush_contract()
        contract_name = label
        contract_debit = debit
        contract_credit = credit

    flush_counterparty()
    return Osv57Sheet(
        root=Osv57Node(
            root_name, "account", _money(root_debit), _money(root_credit), tuple(counterparties)
        ),
        total_debit=_money(total_debit),
        total_credit=_money(total_credit),
    )


def read_card51(path: Path) -> Card51Sheet:
    """Карточка счёта 51: строки с датой, документом, корреспонденцией и суммами."""
    sheet = _open_sheet(path)
    header = _header_row(sheet, "Период")
    rows: list[Card51Row] = []
    opening: Decimal | None = None
    turnover_debit: Decimal | None = None
    turnover_credit: Decimal | None = None
    closing: Decimal | None = None

    for row in range(header + 2, sheet.nrows):
        label = _text(sheet, row, 0)
        if not label:
            continue
        if label.startswith(SALDO_PREFIX):
            amount = cell_amount(sheet.cell_value(row, CARD_BALANCE_COL))
            if opening is None:
                opening = amount
            else:
                closing = amount
            continue
        if label.startswith("Обороты за период"):
            turnover_debit = cell_amount(sheet.cell_value(row, CARD_TURNOVER_DEBIT_COL))
            turnover_credit = cell_amount(sheet.cell_value(row, CARD_TURNOVER_CREDIT_COL))
            tail = cell_amount(sheet.cell_value(row, CARD_BALANCE_COL))
            if closing is None:
                closing = tail
            continue
        business_date = _parse_dmy(label)
        if business_date is None:
            continue
        rows.append(
            Card51Row(
                business_date=business_date,
                document=_text(sheet, row, 1),
                debit_account=_text(sheet, row, 4),
                credit_account=_text(sheet, row, 7),
                debit_amount=cell_amount(sheet.cell_value(row, CARD_DEBIT_AMOUNT_COL)),
                credit_amount=cell_amount(sheet.cell_value(row, CARD_CREDIT_AMOUNT_COL)),
                running_balance=cell_amount(sheet.cell_value(row, CARD_BALANCE_COL)),
            )
        )
    if not rows:
        raise XlsFormatError("карточка 51 без строк операций")
    return Card51Sheet(
        opening_balance=opening,
        rows=tuple(rows),
        turnover_debit=turnover_debit,
        turnover_credit=turnover_credit,
        closing_balance=closing,
    )


def _parse_dmy(raw: str) -> date | None:
    text = raw.strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
