import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import StringIO

from app.domain.budget import metrics_for
from app.domain.imports.contracts import ImportFormatError
from app.domain.imports.import_meta import parse_row_meta, validate_import_header
from app.domain.imports.normalize import decode_text
from app.domain.money import money

BUDGET_COLUMNS = (
    "year",
    "month",
    "basis",
    "metric_type",
    "category_code",
    "direction_code",
    "amount",
    "distribution_method",
)


@dataclass(frozen=True)
class BudgetLine:
    row_number: int
    year: int | None
    month: int | None
    basis: str
    metric_type: str
    category_code: str
    direction_code: str
    amount: Decimal | None
    distribution_method: str
    external_id: str
    errors: tuple[str, ...]
    raw: dict[str, str]

    def canonical(self) -> dict[str, str]:
        amount = "" if self.amount is None else format(self.amount, "f")
        return {
            "year": "" if self.year is None else str(self.year),
            "month": "" if self.month is None else str(self.month),
            "basis": self.basis,
            "metric_type": self.metric_type,
            "category_code": self.category_code,
            "direction_code": self.direction_code,
            "amount": amount,
            "distribution_method": self.distribution_method,
        }


def read_budget_csv(content: bytes, *, encoding: str, max_rows: int) -> list[BudgetLine]:
    text = decode_text(content, encoding)
    reader = csv.reader(StringIO(text))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ImportFormatError("unsupported_format", "Пустой файл") from exc
    columns = validate_import_header(tuple(item.strip() for item in header), BUDGET_COLUMNS)
    lines: list[BudgetLine] = []
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
            line = BudgetLine(
                line.row_number,
                line.year,
                line.month,
                line.basis,
                line.metric_type,
                line.category_code,
                line.direction_code,
                line.amount,
                line.distribution_method,
                line.external_id,
                line.errors + ("duplicate_external_id",),
                line.raw,
            )
        if line.external_id:
            seen.add(line.external_id)
        lines.append(line)
    return lines


def _normalize(raw: dict[str, str], row_number: int) -> BudgetLine:
    errors: list[str] = []
    operation_hint = raw.get("operation", "").strip().lower()
    if operation_hint == "unpost":
        meta = parse_row_meta(raw)
        return BudgetLine(
            row_number,
            None,
            None,
            "",
            "",
            "",
            "",
            None,
            "",
            meta.external_id,
            tuple(dict.fromkeys([*errors, *meta.errors])),
            dict(raw),
        )
    year = _year(raw.get("year", ""), errors)
    month = _month(raw.get("month", ""), errors)
    basis = raw.get("basis", "").strip()
    if basis not in {"cash", "revenue"}:
        errors.append("bad_basis")
    metric = raw.get("metric_type", "").strip()
    if metric not in {"cash_in", "cash_out", "revenue"}:
        errors.append("bad_metric")
    elif basis in {"cash", "revenue"} and metric not in metrics_for(basis):
        errors.append("basis_metric")
    method = raw.get("distribution_method", "").strip()
    if method != "calendar_days":
        errors.append("bad_distribution")
    amount = _money(raw.get("amount", ""), errors)
    category = raw.get("category_code", "").strip()
    direction = raw.get("direction_code", "").strip()
    external_id = ""
    if year is not None and month is not None and basis and metric:
        external_id = f"{year}:{month}:{basis}:{metric}:{category}:{direction}"
    meta = parse_row_meta(raw, external_id=external_id or None)
    errors.extend(meta.errors)
    if meta.external_id:
        external_id = meta.external_id
    if not external_id:
        errors.append("missing_external_id")
    return BudgetLine(
        row_number,
        year,
        month,
        basis,
        metric,
        category,
        direction,
        amount,
        method,
        external_id,
        tuple(errors),
        dict(raw),
    )


def _year(raw: str, errors: list[str]) -> int | None:
    text = raw.strip()
    if not text.isdigit() or not 2000 <= int(text) <= 2100:
        errors.append("bad_year")
        return None
    return int(text)


def _month(raw: str, errors: list[str]) -> int | None:
    text = raw.strip()
    if not text.isdigit() or not 1 <= int(text) <= 12:
        errors.append("bad_month")
        return None
    return int(text)


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
    if value != money(value) or value < 0:
        errors.append("bad_amount")
        return None
    return money(value)
