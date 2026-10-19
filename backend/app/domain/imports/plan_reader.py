import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO

from app.domain.imports.contracts import ImportFormatError
from app.domain.imports.import_meta import parse_row_meta, validate_import_header
from app.domain.imports.normalize import decode_text
from app.domain.money import money

PLAN_COLUMNS = (
    "external_id",
    "direction",
    "amount",
    "currency",
    "due_date",
    "expected_date",
    "category_code",
    "counterparty_inn",
    "confidence",
    "priority",
    "wallet_code",
)
CONFIDENCE = {"confirmed", "expected", "tentative"}
PRIORITY = {"critical", "high", "normal", "low"}


@dataclass(frozen=True)
class PlanLine:
    row_number: int
    external_id: str
    direction: str
    amount: Decimal | None
    currency: str
    due_date: date | None
    expected_date: date | None
    category_code: str
    counterparty_inn: str
    confidence: str
    priority: str
    wallet_code: str
    errors: tuple[str, ...]
    raw: dict[str, str]

    def canonical(self) -> dict[str, str]:
        due = "" if self.due_date is None else self.due_date.isoformat()
        expected = "" if self.expected_date is None else self.expected_date.isoformat()
        return {
            "external_id": self.external_id,
            "direction": self.direction,
            "amount": "" if self.amount is None else format(self.amount, "f"),
            "currency": self.currency,
            "due_date": due,
            "expected_date": expected,
            "category_code": self.category_code,
            "counterparty_inn": self.counterparty_inn,
            "confidence": self.confidence,
            "priority": self.priority,
            "wallet_code": self.wallet_code,
        }


def read_plan_csv(content: bytes, *, encoding: str, max_rows: int) -> list[PlanLine]:
    text = decode_text(content, encoding)
    reader = csv.reader(StringIO(text))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ImportFormatError("unsupported_format", "Пустой файл") from exc
    columns = validate_import_header(tuple(item.strip() for item in header), PLAN_COLUMNS)
    lines: list[PlanLine] = []
    seen: set[str] = set()
    for index, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(lines) >= max_rows:
            raise ImportFormatError("unsupported_format", "Слишком много строк")
        padded = list(row) + [""] * (len(columns) - len(row))
        raw = {column: padded[pos] for pos, column in enumerate(columns)}
        line = _normalize(raw, index)
        if line.external_id and line.external_id in seen:
            line = PlanLine(
                line.row_number,
                line.external_id,
                line.direction,
                line.amount,
                line.currency,
                line.due_date,
                line.expected_date,
                line.category_code,
                line.counterparty_inn,
                line.confidence,
                line.priority,
                line.wallet_code,
                line.errors + ("duplicate_external_id",),
                line.raw,
            )
        if line.external_id:
            seen.add(line.external_id)
        lines.append(line)
    return lines


def _normalize(raw: dict[str, str], row_number: int) -> PlanLine:
    meta = parse_row_meta(raw)
    errors: list[str] = list(meta.errors)
    if meta.operation == "unpost":
        return PlanLine(
            row_number,
            meta.external_id,
            "",
            None,
            "",
            None,
            None,
            "",
            "",
            "expected",
            "normal",
            "",
            tuple(errors),
            dict(raw),
        )
    external_id = meta.external_id
    if not external_id:
        errors.append("missing_external_id")
    direction = raw.get("direction", "").strip()
    if direction not in {"in", "out"}:
        errors.append("bad_direction")
    currency = raw.get("currency", "").strip()
    if currency != "RUB":
        errors.append("bad_currency")
    confidence = raw.get("confidence", "").strip()
    if confidence not in CONFIDENCE:
        errors.append("bad_confidence")
    priority = raw.get("priority", "").strip()
    if priority not in PRIORITY:
        errors.append("bad_priority")
    amount = _money(raw.get("amount", ""), errors)
    due = _date(raw.get("due_date", ""), errors)
    expected = _date(raw.get("expected_date", ""), errors)
    return PlanLine(
        row_number,
        external_id,
        direction,
        amount,
        currency,
        due,
        expected,
        raw.get("category_code", "").strip(),
        raw.get("counterparty_inn", "").strip(),
        confidence,
        priority,
        raw.get("wallet_code", "").strip(),
        tuple(errors),
        dict(raw),
    )


def _money(raw: str, errors: list[str]) -> Decimal | None:
    text = raw.strip().replace(" ", "")
    if not text:
        errors.append("bad_amount")
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        errors.append("bad_amount")
        return None
    if value != money(value) or value <= 0:
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
