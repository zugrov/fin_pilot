import csv
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO

from app.domain.imports.contracts import ImportFormatError
from app.domain.imports.normalize import decode_text
from app.domain.money import money

BALANCES_COLUMNS = ("wallet_code", "as_of", "balance", "currency")
STRICT_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_INVALID_AMOUNT_TOKENS = frozenset(
    {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}
)


@dataclass(frozen=True)
class BalancesLine:
    row_number: int
    wallet_code: str
    as_of: date | None
    balance: Decimal | None
    currency: str
    errors: tuple[str, ...]
    raw: dict[str, str]

    def canonical(self) -> dict[str, str]:
        as_of = "" if self.as_of is None else self.as_of.isoformat()
        amount = "" if self.balance is None else format(self.balance, "f")
        return {
            "wallet_code": self.wallet_code,
            "as_of": as_of,
            "balance": amount,
            "currency": self.currency,
        }


def read_balances_csv(content: bytes, *, encoding: str, max_rows: int) -> list[BalancesLine]:
    text = decode_text(content, encoding)
    reader = csv.reader(StringIO(text))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ImportFormatError("unsupported_format", "Пустой файл") from exc
    if tuple(item.strip() for item in header) != BALANCES_COLUMNS:
        raise ImportFormatError("unsupported_format", "Неизвестные колонки CSV")
    lines: list[BalancesLine] = []
    for index, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(lines) >= max_rows:
            raise ImportFormatError("unsupported_format", "Слишком много строк")
        padded = list(row) + [""] * (len(BALANCES_COLUMNS) - len(row))
        raw = {column: padded[pos].strip() for pos, column in enumerate(BALANCES_COLUMNS)}
        lines.append(normalize_balances_line(raw, index))
    return lines


def normalize_balances_line(raw: dict[str, str], row_number: int) -> BalancesLine:
    cleaned = {column: str(raw.get(column, "")).strip() for column in BALANCES_COLUMNS}
    return _normalize(cleaned, row_number)


def duplicate_wallet_codes(lines: list[BalancesLine]) -> set[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for line in lines:
        code = line.wallet_code.strip()
        if not code or line.errors:
            continue
        if code in seen:
            dupes.add(code)
        seen.add(code)
    return dupes


def _normalize(raw: dict[str, str], row_number: int) -> BalancesLine:
    errors: list[str] = []
    wallet_code = raw.get("wallet_code", "").strip()
    if not wallet_code:
        errors.append("missing_wallet_code")
    as_of = _parse_date(raw.get("as_of", ""), errors)
    balance = _parse_balance(raw.get("balance", ""), errors)
    currency = raw.get("currency", "").strip().upper()
    if not currency:
        errors.append("missing_currency")
    elif currency != "RUB":
        errors.append("unsupported_currency")
    return BalancesLine(
        row_number=row_number,
        wallet_code=wallet_code,
        as_of=as_of,
        balance=balance,
        currency=currency,
        errors=tuple(errors),
        raw=raw,
    )


def _parse_date(raw: str, errors: list[str]) -> date | None:
    value = raw.strip()
    if not value:
        errors.append("missing_date")
        return None
    if not STRICT_DATE.match(value):
        errors.append("invalid_date")
        return None
    try:
        parts = value.split("-")
        parsed = date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, TypeError):
        errors.append("invalid_date")
        return None
    if parsed.isoformat() != value:
        errors.append("invalid_date")
        return None
    return parsed


def _parse_balance(raw: str, errors: list[str]) -> Decimal | None:
    value = raw.strip()
    if not value:
        errors.append("missing_amount")
        return None
    token = value.lower()
    if token in _INVALID_AMOUNT_TOKENS:
        errors.append("invalid_amount")
        return None
    if "e" in token:
        errors.append("invalid_amount")
        return None
    try:
        amount = Decimal(value)
    except InvalidOperation:
        errors.append("invalid_amount")
        return None
    if not amount.is_finite():
        errors.append("invalid_amount")
        return None
    if amount != money(amount):
        errors.append("invalid_amount_precision")
        return None
    return money(amount)
