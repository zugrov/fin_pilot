from datetime import date
from decimal import Decimal
from pathlib import Path

from app.domain.imports.clientbank import read_clientbank, statement_period_end
from app.domain.imports.contracts import ImportFormatError
from app.domain.imports.csv_reader import read_csv
from app.domain.imports.dedup import classify_duplicate
from app.domain.imports.detect import detect_format
from app.domain.imports.normalize import escape_spreadsheet_text, payload_digest
from app.domain.imports.rules import RuleView, matching_category
from app.domain.imports.xlsx_reader import read_xlsx

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"


def test_csv_contract_and_two_same_payments_stay_distinct() -> None:
    lines = read_csv((FIXTURES / "cash_ok.csv").read_bytes(), encoding="utf-8", max_rows=100)
    assert len(lines) == 2
    assert lines[0].errors == ()
    assert lines[0].amount == Decimal("1500.00")
    assert lines[0].external_id != lines[1].external_id
    assert payload_digest(lines[0]) != payload_digest(lines[1])


def test_unknown_format_is_rejected() -> None:
    content = (FIXTURES / "unknown.txt").read_bytes()
    try:
        detect_format(content, "csv", "utf-8")
        raised = False
    except ImportFormatError as exc:
        raised = exc.code == "unsupported_format"
    assert raised is True


def test_clientbank_version_and_direction() -> None:
    lines = read_clientbank(
        (FIXTURES / "clientbank_ok.txt").read_bytes(),
        encoding="utf-8",
        max_rows=10,
        wallet_code="main",
    )
    assert lines[0].direction == "in"
    assert lines[0].amount == Decimal("1500.00")
    assert lines[0].external_id == "cb-1"
    try:
        read_clientbank(
            (FIXTURES / "clientbank_old.txt").read_bytes(),
            encoding="utf-8",
            max_rows=10,
            wallet_code="main",
        )
        raised = False
    except ImportFormatError:
        raised = True
    assert raised is True


def test_xlsx_formula_without_value_is_a_row_error() -> None:
    lines = read_xlsx(
        (FIXTURES / "cash_formula.xlsx").read_bytes(),
        max_rows=10,
        max_uncompressed=1_000_000,
    )
    assert "formula_without_value" in lines[0].errors
    good = read_xlsx(
        (FIXTURES / "cash_ok.xlsx").read_bytes(),
        max_rows=10,
        max_uncompressed=1_000_000,
    )
    assert good[0].errors == ()
    assert good[0].amount == Decimal("1500.00")


def test_dedup_outcomes() -> None:
    assert classify_duplicate(
        has_errors=False,
        identity_hash="a",
        payload_hash="a",
        other_ids=(),
        authoritative=True,
    ) == ("repeated", "skip")
    assert classify_duplicate(
        has_errors=False,
        identity_hash="a",
        payload_hash="b",
        other_ids=(),
        authoritative=True,
    ) == ("changed", "revise")
    assert classify_duplicate(
        has_errors=False,
        identity_hash=None,
        payload_hash="b",
        other_ids=("tx-1",),
        authoritative=True,
    ) == ("linked", "link")
    assert classify_duplicate(
        has_errors=False,
        identity_hash=None,
        payload_hash="b",
        other_ids=("tx-1", "tx-2"),
        authoritative=True,
    ) == ("ambiguous", "review")
    assert classify_duplicate(
        has_errors=True,
        identity_hash=None,
        payload_hash="",
        other_ids=(),
        authoritative=True,
    ) == ("invalid", "skip")


def test_rule_skips_when_conditions_miss() -> None:
    rule = RuleView(1, True, {"description_contains": "аренда", "direction": "out"}, "operating")
    assert (
        matching_category(
            (rule,),
            description="Оплата: аренда офиса",
            counterparty_inn="",
            direction="out",
            amount=Decimal("10.00"),
        )
        == "operating"
    )
    assert (
        matching_category(
            (rule,),
            description="Оплата аренды",
            counterparty_inn="",
            direction="in",
            amount=Decimal("10.00"),
        )
        is None
    )


def test_statement_end_is_not_the_receive_date() -> None:
    content = (
        "1CClientBankExchange\nВерсияФормата=1.03\nДатаКонца=13.10.2026\nКонецФайла\n"
    ).encode()
    assert statement_period_end(content, encoding="utf-8") == date(2026, 10, 13)
    assert read_clientbank(content, encoding="utf-8", max_rows=10, wallet_code="main") == []
    empty = "1CClientBankExchange\nВерсияФормата=1.03\nКонецФайла\n".encode()
    try:
        read_clientbank(empty, encoding="utf-8", max_rows=10, wallet_code="main")
        raised = False
    except ImportFormatError as exc:
        raised = exc.code == "unsupported_format"
    assert raised is True


def test_spreadsheet_text_is_escaped() -> None:
    assert escape_spreadsheet_text("=1+1") == "'=1+1"
    assert escape_spreadsheet_text("аренда") == "аренда"
