"""Суточные секции остатков ClientBank (отдельно от read_clientbank)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.domain.imports.normalize import decode_text


@dataclass(frozen=True)
class ClientBankDailySection:
    period_start: date
    period_end: date
    account: str
    opening: Decimal
    total_in: Decimal
    total_out: Decimal
    closing: Decimal


def parse_clientbank_daily_sections(
    content: bytes,
    *,
    encoding: str,
) -> list[ClientBankDailySection]:
    text = decode_text(content, encoding)
    lines = [item.strip() for item in text.splitlines() if item.strip()]
    sections: list[ClientBankDailySection] = []
    in_section = False
    buf: dict[str, str] = {}
    for item in lines:
        if item.startswith("СекцияРасчСчет"):
            in_section = True
            buf = {}
            continue
        if item == "КонецРасчСчет":
            if buf:
                sections.append(_section_from_buf(buf))
            in_section = False
            buf = {}
            continue
        if in_section and "=" in item:
            key, value = item.split("=", 1)
            buf[key] = value
    return sections


def _section_from_buf(buf: dict[str, str]) -> ClientBankDailySection:
    return ClientBankDailySection(
        period_start=_parse_date(buf.get("ДатаНачала", "")),
        period_end=_parse_date(buf.get("ДатаКонца", "")),
        account=buf.get("РасчСчет", "").strip(),
        opening=_parse_amount(buf.get("НачальныйОстаток", "0")),
        total_in=_parse_amount(buf.get("ВсегоПоступило", "0")),
        total_out=_parse_amount(buf.get("ВсегоСписано", "0")),
        closing=_parse_amount(buf.get("КонечныйОстаток", "0")),
    )


def _parse_date(raw: str) -> date:
    text = raw.strip()
    if not text:
        raise ValueError("empty date in ClientBank daily section")
    return datetime.strptime(text, "%d.%m.%Y").date()


def _parse_amount(raw: str) -> Decimal:
    text = raw.strip().replace(" ", "").replace(",", ".")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: {raw!r}") from exc
