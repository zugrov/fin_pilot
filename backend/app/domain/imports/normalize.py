import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.domain.imports.contracts import CASH_COLUMNS, ImportFormatError, ImportLine
from app.domain.imports.import_meta import parse_row_meta
from app.domain.money import money


def decode_text(content: bytes, encoding: str) -> str:
    if encoding not in {"utf-8", "utf-8-sig", "cp1251"}:
        raise ImportFormatError("unsupported_format", "Неизвестная кодировка")
    try:
        return content.decode(encoding)
    except UnicodeDecodeError as exc:
        raise ImportFormatError(
            "unsupported_format", "Файл не читается в заявленной кодировке"
        ) from exc


def escape_spreadsheet_text(value: str) -> str:
    if value[:1] in "=+-@":
        return "'" + value
    return value


def payload_digest(line: ImportLine) -> str:
    raw = json.dumps(line.canonical(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def fingerprint(line: ImportLine) -> str:
    if line.business_date is None or line.amount is None or line.direction not in {"in", "out"}:
        return ""
    raw = "|".join(
        [
            line.business_date.isoformat(),
            format(line.amount, "f"),
            line.direction,
            line.currency,
            line.wallet_code,
            line.description,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_row(raw: dict[str, str], row_number: int, *, date_style: str) -> ImportLine:
    meta = parse_row_meta(raw)
    errors: list[str] = list(meta.errors)
    if meta.operation == "unpost":
        return ImportLine(
            row_number,
            meta.external_id,
            "",
            None,
            "",
            None,
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            tuple(errors),
            dict(raw),
        )
    moment = _date(raw.get("business_date", ""), date_style, errors)
    direction = raw.get("direction", "").strip()
    if direction not in {"in", "out"}:
        errors.append("bad_direction")
    amount = _amount(raw.get("amount", ""), errors)
    currency = raw.get("currency", "").strip()
    if currency != "RUB":
        errors.append("bad_currency")
    external_id = meta.external_id
    if not external_id:
        errors.append("missing_external_id")
    wallet_code = raw.get("wallet_code", "").strip()
    if not wallet_code:
        errors.append("missing_wallet")
    return ImportLine(
        row_number,
        external_id,
        wallet_code,
        moment,
        direction,
        amount,
        currency,
        raw.get("counterparty_inn", "").strip(),
        raw.get("counterparty_name", "").strip(),
        raw.get("description", "").strip(),
        raw.get("document_number", "").strip(),
        raw.get("category_code", "").strip(),
        raw.get("direction_code", "").strip(),
        tuple(errors),
        dict(raw),
    )


def cell_text(value: object) -> tuple[str, str | None]:
    if value is None:
        return "", None
    if isinstance(value, datetime):
        return value.date().isoformat(), None
    if isinstance(value, date):
        return value.isoformat(), None
    if isinstance(value, bool):
        return "", "bad_cell"
    if isinstance(value, float):
        return "", "amount_as_float"
    if isinstance(value, int):
        return str(value), None
    if isinstance(value, str) and value.startswith("="):
        return "", "formula_without_value"
    return str(value).strip(), None


def _date(raw: str, style: str, errors: list[str]) -> date | None:
    text = raw.strip()
    if not text:
        errors.append("bad_date")
        return None
    try:
        if style == "YYYY-MM-DD":
            return date.fromisoformat(text)
        if style == "DD.MM.YYYY":
            day, month, year = text.split(".")
            return date(int(year), int(month), int(day))
    except ValueError:
        errors.append("bad_date")
        return None
    errors.append("bad_date")
    return None


def _amount(raw: str, errors: list[str]) -> Decimal | None:
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
