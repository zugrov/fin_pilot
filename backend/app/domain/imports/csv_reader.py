import csv
from io import StringIO

from app.domain.imports.contracts import CASH_COLUMNS, ImportFormatError, ImportLine
from app.domain.imports.normalize import decode_text, normalize_row


def read_csv(content: bytes, *, encoding: str, max_rows: int) -> list[ImportLine]:
    text = decode_text(content, encoding)
    reader = csv.reader(StringIO(text))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ImportFormatError("unsupported_format", "Пустой файл") from exc
    if tuple(item.strip() for item in header) != CASH_COLUMNS:
        raise ImportFormatError("unsupported_format", "Неизвестные колонки CSV")
    lines: list[ImportLine] = []
    for index, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(lines) >= max_rows:
            raise ImportFormatError("unsupported_format", "Слишком много строк")
        padded = list(row) + [""] * (len(CASH_COLUMNS) - len(row))
        raw = {column: padded[pos] for pos, column in enumerate(CASH_COLUMNS)}
        lines.append(normalize_row(raw, index, date_style="YYYY-MM-DD"))
    return lines
