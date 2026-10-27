"""ClientBank 1.03: структура реальных выгрузок (FA-R03.2a), синтетика cp1251."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.domain.imports.clientbank import read_clientbank, statement_period_end

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"
PROFILE = FIXTURES / "clientbank_export_profile.cp1251.txt"


def _profile_bytes() -> bytes:
    return PROFILE.read_bytes()


def test_export_profile_cp1251_direction_and_ids() -> None:
    lines = read_clientbank(_profile_bytes(), encoding="cp1251", max_rows=50, wallet_code="main")
    assert len(lines) == 5
    assert all(line.errors == () for line in lines)
    by_amount = {line.amount: line for line in lines if line.amount is not None}
    assert by_amount[Decimal("500.00")].direction == "in"
    assert by_amount[Decimal("250.00")].direction == "in"
    assert by_amount[Decimal("200.00")].direction == "out"
    ids = [line.external_id for line in lines]
    assert len(set(ids)) == len(ids) or any("~" in item for item in ids)
    dup = [line for line in lines if line.amount == Decimal("500.00")]
    assert len(dup) == 2
    assert dup[0].external_id != dup[1].external_id
    assert dup[1].external_id.endswith("~2")
    assert dup[1].raw.get("possible_duplicate") == "1"
    same_number = [line for line in lines if line.document_number == "100"]
    assert len(same_number) == 3
    assert len({line.external_id for line in same_number[:2]}) == 2


def test_export_profile_daily_balance_chain() -> None:
    text = _profile_bytes().decode("cp1251")
    rows = [line.strip() for line in text.splitlines() if line.strip()]
    sections: list[dict[str, str]] = []
    buf: dict[str, str] = {}
    in_acc = False
    for item in rows:
        if item.startswith("СекцияРасчСчет"):
            in_acc = True
            buf = {}
            continue
        if item == "КонецРасчСчет":
            sections.append(buf)
            in_acc = False
            continue
        if in_acc and "=" in item:
            k, v = item.split("=", 1)
            buf[k] = v
    assert len(sections) == 2
    assert Decimal(sections[0]["НачальныйОстаток"]) == Decimal("1000.00")
    assert Decimal(sections[0]["КонечныйОстаток"]) == Decimal("1750.00")
    assert Decimal(sections[1]["НачальныйОстаток"]) == Decimal("1750.00")
    assert Decimal(sections[1]["КонечныйОстаток"]) == Decimal("1549.00")


def test_export_profile_document_section_kinds() -> None:
    text = _profile_bytes().decode("cp1251")
    kinds = []
    for line in text.splitlines():
        if line.startswith("СекцияДокумент="):
            kinds.append(line.split("=", 1)[1])
    assert "Платежное поручение" in kinds
    assert "Банковский ордер" in kinds
    assert "-прочее" in kinds


def test_statement_period_end_from_profile() -> None:
    assert statement_period_end(_profile_bytes(), encoding="cp1251") is not None


def test_direction_conflict_when_date_and_account_disagree() -> None:
    body = (
        "1CClientBankExchange\n"
        "ВерсияФормата=1.03\n"
        "СекцияРасчСчет\n"
        "РасчСчет=40702810999900000001\n"
        "КонецРасчСчет\n"
        "СекцияДокумент=Платежное поручение\n"
        "Номер=1\n"
        "Дата=01.09.2026\n"
        "Сумма=10.00\n"
        "Плательщик=ORG EXT\n"
        "ПлательщикИНН=7700000001\n"
        "ПлательщикРасчСчет=40702810888800000001\n"
        "Получатель=ORG OWN\n"
        "ПолучательИНН=7700000099\n"
        "ПолучательРасчСчет=40702810999900000001\n"
        "НазначениеПлатежа=x\n"
        "ДатаПоступило=01.09.2026\n"
        "ДатаСписано=\n"
        "КонецДокумента\n"
        "КонецФайла\n"
    ).encode("cp1251")
    lines = read_clientbank(body, encoding="cp1251", max_rows=10, wallet_code="main")
    assert len(lines) == 1
    assert lines[0].direction == "in"
    assert lines[0].errors == ()

    edited = body.decode("cp1251")
    edited = edited.replace(
        "ПолучательРасчСчет=40702810999900000001",
        "ПолучательРасчСчет=40702810888800000099",
    )
    edited = edited.replace(
        "ПлательщикРасчСчет=40702810888800000001",
        "ПлательщикРасчСчет=40702810999900000001",
    )
    conflict = edited.encode("cp1251")
    bad = read_clientbank(conflict, encoding="cp1251", max_rows=10, wallet_code="main")
    assert "direction_conflict" in bad[0].errors
