"""Инструмент проверки месяца FA-R03 на синтетических данных (без клиентских файлов)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from app.domain.imports.fa_r03.xls_reader import Card51Row, Card51Sheet
from app.tools.fa_r03_check import (
    CardAggregate,
    S1Document,
    aggregate_card,
    find_samples,
    match_aggregates,
    match_by_document_number,
    parse_acquiring,
    predict_section,
    section_for_account,
    template_description,
)


def _doc(
    *,
    direction: str = "in",
    day: str = "2026-09-01",
    amount: str = "1000.00",
    number: str = "1",
    description: str = "",
    inn: str = "",
) -> S1Document:
    return S1Document(
        direction=direction,
        business_date=date.fromisoformat(day),
        amount=Decimal(amount),
        document_number=number,
        description=description,
        counterparty_inn=inn,
    )


class TestSectionForAccount:
    def test_inbound_accounts(self) -> None:
        assert section_for_account("62.02", "in") == "operating"
        assert section_for_account("57.03", "in") == "operating"
        assert section_for_account("90.01.1", "in") == "operating"
        assert section_for_account("55.03", "in") == "investing"
        assert section_for_account("91.01", "in") == "investing"

    def test_outbound_accounts(self) -> None:
        assert section_for_account("60.01", "out") == "operating"
        assert section_for_account("70", "out") == "operating"
        assert section_for_account("91.02", "out") == "operating"
        assert section_for_account("55.03", "out") == "investing"
        assert section_for_account("50.01", "out") == "technical"

    def test_unknown_account(self) -> None:
        assert section_for_account("76.05", "in") is None

    def test_direction_matters(self) -> None:
        assert section_for_account("55.03", "in") == "investing"
        assert section_for_account("55.03", "out") == "investing"
        assert section_for_account("50.01", "in") is None


class TestTemplateDescription:
    def test_digits_replaced(self) -> None:
        assert template_description("Оплата по счету 11859 от 31.08.2026") == (
            "Оплата по счету # от #.#.#"
        )

    def test_empty(self) -> None:
        assert template_description("") == "—"
        assert template_description("12345") == "#"

    def test_collapses_whitespace(self) -> None:
        assert template_description("Два   пробела\nи перевод") == "Два пробела и перевод"


class TestParseAcquiring:
    def test_colon_format(self) -> None:
        text = "ЗА 31/08/2026;КОЛ-ВО:11;СУММА:7645.00,В Т.Ч.УСЛ.БАНКА:173.50"
        assert parse_acquiring(text, net=Decimal("7471.50")) == (
            Decimal("7645.00"),
            Decimal("173.50"),
        )

    def test_alt_format_whole_gross(self) -> None:
        text = (
            "Реестр № 99996323, Дата 01.09.2026 - 01.09.2026, Кол 49, "
            "Сумма 17098, Усл 504,47. В тч НДС"
        )
        assert parse_acquiring(text, net=Decimal("16593.53")) == (
            Decimal("17098.00"),
            Decimal("504.47"),
        )

    def test_alt_format_fractional_gross(self) -> None:
        text = (
            "Реестр № 99996323, Дата 31.08.2026 - 01.09.2026, Кол 56, "
            "Сумма 21833,94, Усл 644,17. В тч НДС"
        )
        assert parse_acquiring(text, net=Decimal("21189.77")) == (
            Decimal("21833.94"),
            Decimal("644.17"),
        )

    def test_single_decimal_fee(self) -> None:
        text = (
            "Реестр № 1, Дата 04.09.2026 - 07.09.2026, Кол 180, "
            "Сумма 69811,34, Усл 2059,7. В тч НДС"
        )
        assert parse_acquiring(text, net=Decimal("67751.64")) == (
            Decimal("69811.34"),
            Decimal("2059.70"),
        )

    def test_not_acquiring(self) -> None:
        assert parse_acquiring("Оплата по счету № 11859", net=Decimal("100.00")) is None
        assert parse_acquiring("", net=Decimal("100.00")) is None

    def test_amounts_must_reconcile_with_net(self) -> None:
        text = "СУММА:7645.00,В Т.Ч.УСЛ.БАНКА:173.50"
        assert parse_acquiring(text, net=Decimal("9999.99")) is None

    def test_without_net_returns_none(self) -> None:
        assert parse_acquiring("СУММА:7645.00,В Т.Ч.УСЛ.БАНКА:173.50") is None


class TestAggregateCard:
    def _row(
        self,
        *,
        direction: str,
        amount: str,
        counter: str,
        document: str = "Док 1",
        day: str = "2026-09-01",
    ) -> Card51Row:
        debit = Decimal(amount) if direction == "in" else Decimal("0.00")
        credit = Decimal("0.00") if direction == "in" else Decimal(amount)
        return Card51Row(
            business_date=date.fromisoformat(day),
            document=document,
            debit_account="51" if direction == "in" else counter,
            credit_account=counter if direction == "in" else "51",
            debit_amount=debit,
            credit_amount=credit,
            running_balance=Decimal("0.00"),
        )

    def test_single_row_document(self) -> None:
        card = Card51Sheet(
            opening_balance=Decimal("0.00"),
            rows=(self._row(direction="in", amount="1000.00", counter="62.02"),),
            turnover_debit=Decimal("1000.00"),
            turnover_credit=Decimal("0.00"),
            closing_balance=Decimal("1000.00"),
        )
        aggregates = aggregate_card(card)
        assert len(aggregates) == 1
        assert aggregates[0].amount == Decimal("1000.00")
        assert aggregates[0].section == "operating"

    def test_multi_row_document_sums_amounts(self) -> None:
        card = Card51Sheet(
            opening_balance=Decimal("0.00"),
            rows=(
                self._row(direction="out", amount="100.00", counter="60.01"),
                self._row(direction="out", amount="50.00", counter="60.01"),
            ),
            turnover_debit=Decimal("0.00"),
            turnover_credit=Decimal("150.00"),
            closing_balance=Decimal("-150.00"),
        )
        aggregates = aggregate_card(card)
        assert len(aggregates) == 1
        assert aggregates[0].amount == Decimal("150.00")
        assert len(aggregates[0].counter_accounts) == 2

    def test_mixed_accounts_take_majority(self) -> None:
        card = Card51Sheet(
            opening_balance=Decimal("0.00"),
            rows=(
                self._row(direction="out", amount="10.00", counter="60.01"),
                self._row(direction="out", amount="10.00", counter="60.01"),
                self._row(direction="out", amount="10.00", counter="91.02"),
            ),
            turnover_debit=Decimal("0.00"),
            turnover_credit=Decimal("30.00"),
            closing_balance=Decimal("-30.00"),
        )
        assert aggregate_card(card)[0].section == "operating"

    def test_unknown_account_leaves_section_none(self) -> None:
        card = Card51Sheet(
            opening_balance=Decimal("0.00"),
            rows=(self._row(direction="out", amount="10.00", counter="76.05"),),
            turnover_debit=Decimal("0.00"),
            turnover_credit=Decimal("10.00"),
            closing_balance=Decimal("-10.00"),
        )
        assert aggregate_card(card)[0].section is None


class TestMatchByDocumentNumber:
    def _aggregate(
        self, document: str, amount: str = "1000.00", direction: str = "in"
    ) -> CardAggregate:
        return CardAggregate(
            direction=direction,
            business_date=date(2026, 9, 1),
            amount=Decimal(amount),
            document=document,
            counter_accounts=("62.02",),
            section="operating",
        )

    def test_number_inside_document_name(self) -> None:
        doc = _doc(number="420283", amount="1000.00")
        aggregates = [self._aggregate("Списание ТК00-1 от 01.09.2026 по вх.д. 420283")]
        unique, missing, ambiguous = match_by_document_number([doc], aggregates)
        assert (unique, missing, ambiguous) == (1, 0, 0)

    def test_number_absent(self) -> None:
        doc = _doc(number="999", amount="1000.00")
        unique, missing, ambiguous = match_by_document_number([doc], [self._aggregate("Док 1")])
        assert (unique, missing, ambiguous) == (0, 1, 0)

    def test_amount_must_match(self) -> None:
        doc = _doc(number="420283", amount="500.00")
        aggregates = [self._aggregate("по вх.д. 420283", amount="1000.00")]
        assert match_by_document_number([doc], aggregates) == (0, 1, 0)

    def test_ambiguous(self) -> None:
        doc = _doc(number="420283", amount="1000.00")
        aggregates = [
            self._aggregate("по вх.д. 420283"),
            self._aggregate("повтор по вх.д. 420283"),
        ]
        assert match_by_document_number([doc], aggregates) == (0, 0, 1)


class TestMatchAggregates:
    def test_pairs_by_direction_date_amount(self) -> None:
        docs = [_doc(amount="1000.00"), _doc(amount="2000.00", number="2")]
        aggregates = [
            CardAggregate("in", date(2026, 9, 1), Decimal("1000.00"), "A", ("62.02",), "operating"),
            CardAggregate("in", date(2026, 9, 1), Decimal("2000.00"), "B", ("62.02",), "operating"),
        ]
        assert len(match_aggregates(docs, aggregates)) == 2

    def test_does_not_reuse_aggregate(self) -> None:
        docs = [_doc(amount="1000.00", number="1"), _doc(amount="1000.00", number="2")]
        aggregates = [
            CardAggregate("in", date(2026, 9, 1), Decimal("1000.00"), "A", ("62.02",), "operating")
        ]
        assert len(match_aggregates(docs, aggregates)) == 1


class TestPredictSection:
    def test_matches_pack_rule(self) -> None:
        from app.tools.fa_r03_check import pack_rule_views

        rules = pack_rule_views()
        doc = _doc(description="ПРОЦЕНТОВ ПО ДЕПОЗИТУ", direction="in")
        assert predict_section(rules, doc) == "investing"

    def test_no_match_is_unknown(self) -> None:
        from app.tools.fa_r03_check import pack_rule_views

        rules = pack_rule_views()
        doc = _doc(description="011365", direction="in")
        assert predict_section(rules, doc) == "unknown"


class TestFindSamples:
    def test_finds_by_prefix(self, tmp_path) -> None:
        (tmp_path / "S1_bank.txt").write_text("x", encoding="utf-8")
        (tmp_path / "S2_card.xls").write_bytes(b"x")
        (tmp_path / "S3_osv.xls").write_bytes(b"x")
        (tmp_path / "S12_osv.xls").write_bytes(b"x")
        samples = find_samples(tmp_path)
        assert samples.s1 is not None and samples.s1.name == "S1_bank.txt"
        assert samples.s2 is not None and samples.s2.name == "S2_card.xls"
        assert samples.s3 is not None and samples.s3.name == "S3_osv.xls"
        assert samples.s12 is not None and samples.s12.name == "S12_osv.xls"

    def test_missing_files_are_none(self, tmp_path) -> None:
        samples = find_samples(tmp_path)
        assert samples.s1 is None and samples.s2 is None

    def test_missing_folder_exits(self, tmp_path) -> None:
        with pytest.raises(SystemExit):
            find_samples(tmp_path / "nope")
