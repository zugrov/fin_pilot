"""FA-R03.2c: чтение .xls, суммы и мост к сверке (без бинарных фикстур)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from app.domain.imports.fa_r03.reconcile import (
    Card51Row,
    StatementDocument,
    account51_totals_equal,
    card51_rows_to_reconcile,
    match_statement_to_card,
    statement_documents_from_s1,
)
from app.domain.imports.fa_r03.xls_reader import (
    Card51Row as XlsCardRow,
)
from app.domain.imports.fa_r03.xls_reader import (
    XlsFormatError,
    cell_amount,
    parse_day_label,
    read_card51,
    read_osv,
    read_osv_5703,
)

BACKEND = Path(__file__).resolve().parents[2]
SAMPLES = BACKEND.parent / "var" / "fa-r03-client-samples"


def _sample(name: str) -> Path:
    return (SAMPLES / name).resolve()


def _has_samples() -> bool:
    return (_sample("S2_card_51_2026-09.xls")).is_file()


class TestCellAmount:
    def test_two_decimals_ok(self) -> None:
        assert cell_amount("1234.56") == Decimal("1234.56")
        assert cell_amount(1234.56) == Decimal("1234.56")
        assert cell_amount("1234,5") == Decimal("1234.50")

    def test_empty_is_zero(self) -> None:
        assert cell_amount("") == Decimal("0.00")
        assert cell_amount(None) == Decimal("0.00")
        assert cell_amount("  ") == Decimal("0.00")

    def test_more_than_two_decimals_rejected(self) -> None:
        with pytest.raises(XlsFormatError):
            cell_amount("1.234")

    def test_non_numeric_rejected(self) -> None:
        with pytest.raises(XlsFormatError):
            cell_amount("Д")
        with pytest.raises(XlsFormatError):
            cell_amount("итого")

    def test_boolean_rejected(self) -> None:
        with pytest.raises(XlsFormatError):
            cell_amount(True)

    def test_spaces_and_nbsp(self) -> None:
        assert cell_amount("1 234.56") == Decimal("1234.56")
        assert cell_amount("1\xa0234.56") == Decimal("1234.56")


class TestDayLabel:
    def test_parses_turnover_label(self) -> None:
        assert parse_day_label("Обороты за 01.09.26") == date(2026, 9, 1)
        assert parse_day_label("Обороты за 30.09.2026") == date(2026, 9, 30)

    def test_non_label_returns_none(self) -> None:
        assert parse_day_label("Основной договор") is None
        assert parse_day_label("Итого") is None
        assert parse_day_label("Обороты за мусор") is None


class TestBridgeToReconcile:
    def test_card_rows_become_reconcile_rows(self) -> None:
        source = [
            XlsCardRow(
                business_date=date(2026, 9, 1),
                document="Поступление на расчетный счет 001",
                debit_account="51",
                credit_account="62.02",
                debit_amount=Decimal("1000.00"),
                credit_amount=Decimal("0.00"),
                running_balance=Decimal("5000.00"),
            ),
            XlsCardRow(
                business_date=date(2026, 9, 2),
                document="Списание с расчетного счета 002",
                debit_account="91.02",
                credit_account="51",
                debit_amount=Decimal("0.00"),
                credit_amount=Decimal("200.00"),
                running_balance=Decimal("4800.00"),
            ),
        ]
        rows = card51_rows_to_reconcile(source)
        assert [row.direction for row in rows] == ["in", "out"]
        assert [row.amount for row in rows] == [Decimal("1000.00"), Decimal("200.00")]
        assert rows[0].document_number == "Поступление на расчетный счет 001"

    def test_blank_document_becomes_none(self) -> None:
        source = [
            XlsCardRow(
                business_date=date(2026, 9, 1),
                document="",
                debit_account="51",
                credit_account="62.02",
                debit_amount=Decimal("10.00"),
                credit_amount=Decimal("0.00"),
                running_balance=Decimal("10.00"),
            )
        ]
        assert card51_rows_to_reconcile(source)[0].document_number is None

    def test_statement_documents_from_s1_like(self) -> None:
        class Fake:
            direction = "in"
            business_date = date(2026, 9, 1)
            amount = Decimal("1500.00")
            document_number = " 123 "

        docs = statement_documents_from_s1([Fake()])
        assert docs == [
            StatementDocument(
                direction="in",
                business_date=date(2026, 9, 1),
                amount=Decimal("1500.00"),
                document_number="123",
            )
        ]

    def test_matching_works_through_bridge(self) -> None:
        class FakeS1:
            direction = "in"
            business_date = date(2026, 9, 1)
            amount = Decimal("1000.00")
            document_number = "001"

        card = [
            XlsCardRow(
                business_date=date(2026, 9, 1),
                document="001",
                debit_account="51",
                credit_account="62.02",
                debit_amount=Decimal("1000.00"),
                credit_amount=Decimal("0.00"),
                running_balance=Decimal("1000.00"),
            )
        ]
        result = match_statement_to_card(
            statement_documents_from_s1([FakeS1()]), card51_rows_to_reconcile(card)
        )
        assert len(result.matched) == 1
        assert not result.unmatched_statement
        assert not result.unmatched_card

    def test_unmatched_statement_stays_unmatched(self) -> None:
        class FakeS1:
            direction = "in"
            business_date = date(2026, 9, 1)
            amount = Decimal("999.00")
            document_number = "999"

        result = match_statement_to_card(
            statement_documents_from_s1([FakeS1()]), card51_rows_to_reconcile([])
        )
        assert not result.matched
        assert len(result.unmatched_statement) == 1

    def test_three_way_totals_zero_tolerance(self) -> None:
        from app.domain.imports.fa_r03.reconcile import Account51Totals

        first = Account51Totals(
            opening=Decimal("100.00"),
            total_in=Decimal("50.00"),
            total_out=Decimal("30.00"),
            closing=Decimal("120.00"),
        )
        same = Account51Totals(
            opening=Decimal("100.00"),
            total_in=Decimal("50.00"),
            total_out=Decimal("30.00"),
            closing=Decimal("120.00"),
        )
        off_by_cent = Account51Totals(
            opening=Decimal("100.00"),
            total_in=Decimal("50.01"),
            total_out=Decimal("30.00"),
            closing=Decimal("120.01"),
        )
        assert account51_totals_equal(first, same)
        assert not account51_totals_equal(first, off_by_cent)


class TestReconcileTypesUnchanged:
    def test_card51_row_defaults(self) -> None:
        row = Card51Row(direction="in", business_date=date(2026, 9, 1), amount=Decimal("1.00"))
        assert row.document_number is None


@pytest.mark.manual
class TestRealSamples:
    """Ручной тест на локальных образцах клиента; в CI пропускается."""

    @pytest.fixture(autouse=True)
    def _require_samples(self) -> None:
        if not _has_samples():
            pytest.skip("нет var/fa-r03-client-samples/ — ручная проверка недоступна")

    def test_card51_totals_and_balance(self) -> None:
        card = read_card51(_sample("S2_card_51_2026-09.xls"))
        assert card.opening_balance == Decimal("481939.83")
        assert card.closing_balance == Decimal("295464.46")
        ins = sum((row.amount for row in card.rows if row.direction == "in"), Decimal("0"))
        outs = sum((row.amount for row in card.rows if row.direction == "out"), Decimal("0"))
        assert ins == card.turnover_debit
        assert outs == card.turnover_credit
        assert card.opening_balance - card.turnover_credit + card.turnover_debit == (
            card.closing_balance
        )

    def test_osv_has_51_and_5703(self) -> None:
        osv = read_osv(_sample("S3_osv_2026-09.xls"))
        acc51 = osv.by_code("51")
        assert acc51 is not None
        acc5703 = osv.by_code("57.03")
        assert acc5703 is not None
        card = read_card51(_sample("S2_card_51_2026-09.xls"))
        assert acc51.turnover_debit == card.turnover_debit
        assert acc51.turnover_credit == card.turnover_credit

    def test_osv_5703_hierarchy_and_days(self) -> None:
        sheet = read_osv_5703(_sample("S12_osv_57.03_2026-09.xls"))
        assert sheet.root.name == "57.03"
        assert len(sheet.root.children) == 2
        assert all(cp.level == "counterparty" for cp in sheet.root.children)
        assert all(contract.daily for cp in sheet.root.children for contract in cp.children)
        daily = sheet.daily_turnovers()
        assert len(daily) == 22
        assert sum(daily.values()) == sheet.root.turnover_debit
