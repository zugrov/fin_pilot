from app.domain.imports.contracts import KNOWN_ENCODINGS, KNOWN_FORMATS, ImportFormatError
from app.domain.imports.normalize import decode_text


def detect_format(content: bytes, declared: str, encoding: str) -> str:
    if declared not in KNOWN_FORMATS or encoding not in KNOWN_ENCODINGS:
        raise ImportFormatError("unsupported_format", "Неизвестный формат")
    sniffed = _sniff(content, encoding)
    if sniffed != declared:
        raise ImportFormatError("unsupported_format", "Содержимое не совпадает с профилем")
    return sniffed


def _sniff(content: bytes, encoding: str) -> str:
    if content.startswith(b"PK\x03\x04"):
        return "xlsx"
    text = decode_text(content, encoding).lstrip("\ufeff").lstrip()
    if text.startswith("1CClientBankExchange"):
        return "clientbank"
    first = text.splitlines()[0] if text else ""
    if first.startswith("external_id,"):
        return "csv"
    raise ImportFormatError("unsupported_format", "Неизвестный формат")
