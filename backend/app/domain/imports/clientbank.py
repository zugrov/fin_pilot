from __future__ import annotations

import hashlib
from datetime import date, datetime

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
    documents = _documents_with_own_account(lines)
    period_end = statement_period_end(content, encoding=encoding)
    if not documents and period_end is None:
        raise ImportFormatError("unsupported_format", "Пустая выписка без даты конца")
    if len(documents) > max_rows:
        raise ImportFormatError("unsupported_format", "Слишком много строк")
    parsed: list[ImportLine] = []
    base_counts: dict[str, int] = {}
    for index, (document, own_account) in enumerate(documents, start=1):
        raw, pre_errors = _document_to_raw(document, own_account, wallet_code)
        base_id = raw["external_id"]
        base_counts[base_id] = base_counts.get(base_id, 0) + 1
        if base_counts[base_id] > 1:
            raw["external_id"] = f"{base_id}~{base_counts[base_id]}"
            raw["possible_duplicate"] = "1"
        line = normalize_row(raw, index, date_style="DD.MM.YYYY")
        for code in pre_errors:
            line = _with_error(line, code)
        parsed.append(line)
    return parsed


def statement_period_end(content: bytes, *, encoding: str) -> date | None:
    """Конец периода из шапки. Дата письма сюда не попадает."""
    text = decode_text(content, encoding)
    lines = [item.strip() for item in text.splitlines() if item.strip()]
    for item in lines:
        if item.startswith("СекцияДокумент="):
            return None
        if not item.startswith("ДатаКонца="):
            continue
        raw = item.split("=", 1)[1].strip()
        try:
            return datetime.strptime(raw, "%d.%m.%Y").date()
        except ValueError as exc:
            raise ImportFormatError("unsupported_format", "Некорректная ДатаКонца") from exc
    return None


def _documents(lines: list[str]) -> list[dict[str, str]]:
    return [doc for doc, _ in _documents_with_own_account(lines)]


def _documents_with_own_account(lines: list[str]) -> list[tuple[dict[str, str], str]]:
    documents: list[tuple[dict[str, str], str]] = []
    own_account = ""
    current: dict[str, str] | None = None
    in_account = False
    account_buf: dict[str, str] = {}
    for item in lines:
        if item.startswith("СекцияРасчСчет"):
            in_account = True
            account_buf = {}
            continue
        if item == "КонецРасчСчет":
            own_account = account_buf.get("РасчСчет", "").strip() or own_account
            in_account = False
            account_buf = {}
            continue
        if in_account:
            if "=" in item:
                key, value = item.split("=", 1)
                account_buf[key] = value
            continue
        if item.startswith("СекцияДокумент="):
            current = {"СекцияДокумент": item.split("=", 1)[1]}
            continue
        if item == "КонецДокумента":
            if current is not None:
                documents.append((current, own_account))
            current = None
            continue
        if current is None or "=" not in item:
            continue
        key, value = item.split("=", 1)
        current[key] = value
    return documents


def _field_nonempty(document: dict[str, str], key: str) -> bool:
    return document.get(key, "").strip() != ""


def _payer_account(document: dict[str, str]) -> str:
    return (document.get("ПлательщикРасчСчет") or document.get("ПлательщикСчет") or "").strip()


def _payee_account(document: dict[str, str]) -> str:
    return (document.get("ПолучательРасчСчет") or document.get("ПолучательСчет") or "").strip()


def _direction_from_dates(document: dict[str, str]) -> str | None:
    has_out = _field_nonempty(document, "ДатаСписано")
    has_in = _field_nonempty(document, "ДатаПоступило")
    if has_out and not has_in:
        return "out"
    if has_in and not has_out:
        return "in"
    return None


def _direction_from_own_account(document: dict[str, str], own_account: str) -> str | None:
    if not own_account:
        return None
    payer = _payer_account(document)
    payee = _payee_account(document)
    if payer == own_account and payee != own_account:
        return "out"
    if payee == own_account and payer != own_account:
        return "in"
    return None


def _resolve_direction(document: dict[str, str], own_account: str) -> tuple[str, tuple[str, ...]]:
    has_out = _field_nonempty(document, "ДатаСписано")
    has_in = _field_nonempty(document, "ДатаПоступило")
    from_account = _direction_from_own_account(document, own_account)
    if (has_out and has_in) or (not has_out and not has_in):
        if from_account:
            return from_account, ()
        return "", ("bad_direction",)
    from_dates = _direction_from_dates(document)
    if from_dates is None:
        return "", ("bad_direction",)
    if from_account and from_account != from_dates:
        return "", ("direction_conflict",)
    return from_dates, ()


def _purpose_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _compose_external_id(
    *,
    own_account: str,
    document: dict[str, str],
    direction: str,
    business_date: str,
    amount: str,
    counterparty_inn: str,
) -> str:
    number = document.get("Номер", "").strip()
    doc_date = document.get("Дата", "").strip() or business_date.strip()
    amount_norm = amount.strip().replace(" ", "")
    purpose = document.get("НазначениеПлатежа", "")
    payload = "|".join(
        [
            own_account,
            number,
            doc_date,
            direction,
            amount_norm,
            counterparty_inn.strip(),
            _purpose_hash(purpose),
        ]
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"cb-{digest[:56]}"


def _document_to_raw(
    document: dict[str, str], own_account: str, wallet_code: str
) -> tuple[dict[str, str], tuple[str, ...]]:
    direction, pre_errors = _resolve_direction(document, own_account)
    name = ""
    inn = ""
    moment = document.get("Дата", "")
    if direction == "out":
        name = document.get("Получатель", "")
        inn = document.get("ПолучательИНН", "")
        moment = document.get("ДатаСписано", "") or moment
    elif direction == "in":
        name = document.get("Плательщик", "")
        inn = document.get("ПлательщикИНН", "")
        moment = document.get("ДатаПоступило", "") or moment
    amount = document.get("Сумма", "")
    external_id = ""
    if direction in {"in", "out"} and not pre_errors:
        external_id = _compose_external_id(
            own_account=own_account,
            document=document,
            direction=direction,
            business_date=moment,
            amount=amount,
            counterparty_inn=inn,
        )
    elif not external_id:
        # Строки с ошибками: номер документа для отчёта импорта (не dedup-ключ).
        external_id = document.get("Номер", "").strip()
    raw = {
        "external_id": external_id,
        "wallet_code": wallet_code,
        "business_date": moment,
        "direction": direction,
        "amount": amount,
        "currency": "RUB",
        "counterparty_inn": inn,
        "counterparty_name": name,
        "description": document.get("НазначениеПлатежа", ""),
        "document_number": document.get("Номер", ""),
        "category_code": "",
        "direction_code": "",
    }
    return raw, pre_errors


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
