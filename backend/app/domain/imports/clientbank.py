from app.domain.imports.contracts import CLIENTBANK_VERSION, ImportFormatError, ImportLine
from app.domain.imports.normalize import decode_text, normalize_row


def read_clientbank(
    content: bytes, *, encoding: str, max_rows: int, wallet_code: str
) -> list[ImportLine]:
    text = decode_text(content, encoding)
    lines = [item.strip() for item in text.splitlines() if item.strip()]
    if not lines or lines[0] != "1CClientBankExchange":
        raise ImportFormatError("unsupported_format", "Это не ClientBankExchange")
    version = ""
    for item in lines:
        if item.startswith("ВерсияФормата="):
            version = item.split("=", 1)[1]
            break
    if version != CLIENTBANK_VERSION:
        raise ImportFormatError("unsupported_format", "Неподдерживаемая версия ClientBankExchange")
    documents = _documents(lines)
    if len(documents) > max_rows:
        raise ImportFormatError("unsupported_format", "Слишком много строк")
    parsed: list[ImportLine] = []
    seen: set[str] = set()
    for index, document in enumerate(documents, start=1):
        raw = _to_cash(document, wallet_code)
        line = normalize_row(raw, index, date_style="DD.MM.YYYY")
        if line.external_id in seen:
            line = _with_error(line, "duplicate_external_id")
        if line.external_id:
            seen.add(line.external_id)
        parsed.append(line)
    return parsed


def _documents(lines: list[str]) -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for item in lines:
        if item.startswith("СекцияДокумент="):
            current = {"СекцияДокумент": item.split("=", 1)[1]}
            continue
        if item == "КонецДокумента":
            if current is not None:
                documents.append(current)
            current = None
            continue
        if current is None or "=" not in item:
            continue
        key, value = item.split("=", 1)
        current[key] = value
    return documents


def _to_cash(document: dict[str, str], wallet_code: str) -> dict[str, str]:
    outgoing = "ДатаСписано" in document
    incoming = "ДатаПоступило" in document
    if outgoing and not incoming:
        direction = "out"
        name = document.get("Получатель", "")
        inn = document.get("ПолучательИНН", "")
        moment = document["ДатаСписано"]
    elif incoming and not outgoing:
        direction = "in"
        name = document.get("Плательщик", "")
        inn = document.get("ПлательщикИНН", "")
        moment = document["ДатаПоступило"]
    else:
        direction = ""
        name = ""
        inn = ""
        moment = document.get("Дата", "")
    return {
        "external_id": document.get("Номер", ""),
        "wallet_code": wallet_code,
        "business_date": moment,
        "direction": direction,
        "amount": document.get("Сумма", ""),
        "currency": "RUB",
        "counterparty_inn": inn,
        "counterparty_name": name,
        "description": document.get("НазначениеПлатежа", ""),
        "document_number": document.get("Номер", ""),
        "category_code": "",
        "direction_code": "",
    }


def _with_error(line: ImportLine, code: str) -> ImportLine:
    return ImportLine(
        line.row_number,
        line.external_id,
        line.wallet_code,
        line.business_date,
        line.direction,
        line.amount,
        line.currency,
        line.counterparty_inn,
        line.counterparty_name,
        line.description,
        line.document_number,
        line.category_code,
        line.direction_code,
        tuple(dict.fromkeys([*line.errors, code])),
        line.raw,
    )
