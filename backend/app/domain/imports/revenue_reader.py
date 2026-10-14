import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO

from app.domain.imports.contracts import ImportFormatError
from app.domain.imports.normalize import decode_text
from app.domain.money import money

REVENUE_COLUMNS = (
    "external_id",
    "recognition_date",
    "document_number",
    "counterparty_inn",
    "amount_ex_vat",
    "vat_amount",
    "amount_inc_vat",
    "entry_type",
    "direction_code",
)


@dataclass(frozen=True)
class RevenueLine:
    row_number: int
    external_id: str
    recognition_date: date | None
    document_number: str
    counterparty_inn: str
    amount_ex_vat: Decimal | None
    vat_amount: Decimal | None
    amount_inc_vat: Decimal | None
    entry_type: str
    direction_code: str
    errors: tuple[str, ...]
    raw: dict[str, str]

    def canonical(self) -> dict[str, str]:
        moment = "" if self.recognition_date is None else self.recognition_date.isoformat()
        return {
            "external_id": self.external_id,
            "recognition_date": moment,
            "document_number": self.document_number,
            "counterparty_inn": self.counterparty_inn,
            "amount_ex_vat": _shown(self.amount_ex_vat),
            "vat_amount": _shown(self.vat_amount),
            "amount_inc_vat": _shown(self.amount_inc_vat),
            "entry_type": self.entry_type,
            "direction_code": self.direction_code,
        }


def read_revenue_csv(
    content: bytes, *, encoding: str, max_rows: int, vat_basis: str
) -> list[RevenueLine]:
    text = decode_text(content, encoding)
    reader = csv.reader(StringIO(text))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ImportFormatError("unsupported_format", "Пустой файл") from exc
    if tuple(item.strip() for item in header) != REVENUE_COLUMNS:
        raise ImportFormatError("unsupported_format", "Неизвестные колонки CSV")
    lines: list[RevenueLine] = []
    seen: set[str] = set()
    for index, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(lines) >= max_rows:
            raise ImportFormatError("unsupported_format", "Слишком много строк")
        padded = list(row) + [""] * (len(REVENUE_COLUMNS) - len(row))
        raw = {column: padded[pos] for pos, column in enumerate(REVENUE_COLUMNS)}
        line = _normalize(raw, index, vat_basis)
        if line.external_id and line.external_id in seen:
            line = RevenueLine(
                line.row_number,
                line.external_id,
                line.recognition_date,
                line.document_number,
                line.counterparty_inn,
                line.amount_ex_vat,
                line.vat_amount,
                line.amount_inc_vat,
                line.entry_type,
                line.direction_code,
                line.errors + ("duplicate_external_id",),
                line.raw,
            )
        if line.external_id:
            seen.add(line.external_id)
        lines.append(line)
    return lines


def _normalize(raw: dict[str, str], row_number: int, vat_basis: str) -> RevenueLine:
    errors: list[str] = []
    moment = _date(raw.get("recognition_date", ""), errors)
    entry_type = raw.get("entry_type", "").strip()
    if entry_type not in {"sale", "return"}:
        errors.append("bad_entry_type")
    external_id = raw.get("external_id", "").strip()
    if not external_id:
        errors.append("missing_external_id")
    ex_vat, vat, inc = _amounts(raw, vat_basis, errors)
    values = {column: raw.get(column, "") for column in REVENUE_COLUMNS}
    return RevenueLine(
        row_number,
        external_id,
        moment,
        raw.get("document_number", "").strip(),
        raw.get("counterparty_inn", "").strip(),
        ex_vat,
        vat,
        inc,
        entry_type,
        raw.get("direction_code", "").strip(),
        tuple(errors),
        values,
    )


def _amounts(
    raw: dict[str, str], vat_basis: str, errors: list[str]
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    inc = _money(raw.get("amount_inc_vat", ""), errors, required=True, allow_zero=False)
    if vat_basis == "unknown" and not raw.get("amount_ex_vat", "").strip():
        return None, None, inc
    ex_vat = _money(raw.get("amount_ex_vat", ""), errors, required=True, allow_zero=True)
    vat = _money(raw.get("vat_amount", ""), errors, required=True, allow_zero=True)
    if ex_vat is not None and vat is not None and inc is not None and ex_vat + vat != inc:
        errors.append("vat_mismatch")
    return ex_vat, vat, inc


def _money(raw: str, errors: list[str], *, required: bool, allow_zero: bool) -> Decimal | None:
    text = raw.strip().replace(" ", "")
    if not text:
        if required:
            errors.append("bad_amount")
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        errors.append("bad_amount")
        return None
    if value != money(value) or value < 0 or (value == 0 and not allow_zero):
        errors.append("bad_amount")
        return None
    return money(value)


def _date(raw: str, errors: list[str]) -> date | None:
    text = raw.strip()
    if not text:
        errors.append("bad_date")
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        errors.append("bad_date")
        return None


def _shown(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value, "f")
