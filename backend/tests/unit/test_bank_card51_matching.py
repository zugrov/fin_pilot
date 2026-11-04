"""Синтетика для FA-R03.2 bank↔card51 matching."""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal

from app.domain.imports.fa_r03.bank_card51_matching import (
    BankMovement,
    aggregate_card_rows,
    match_bank_to_card51,
)
from app.domain.imports.fa_r03.clientbank_daily import ClientBankDailySection
from app.domain.imports.fa_r03.reconcile import daily_chain_errors
from app.domain.imports.fa_r03.xls_reader import Card51Row

ZERO = Decimal("0.00")


def _bank(
    index: int,
    day: str,
    amount: str,
    *,
    direction: str = "in",
    number: str = "1",
) -> BankMovement:
    return BankMovement(
        index=index,
        direction=direction,
        business_date=date.fromisoformat(day),
        amount=Decimal(amount),
        document_number=number,
    )


def _card_row(
    day: str,
    amount: str,
    document: str,
    counter: str,
    *,
    direction: str = "in",
) -> Card51Row:
    if direction == "in":
        return Card51Row(
            business_date=date.fromisoformat(day),
            document=document,
            debit_account="51",
            credit_account=counter,
            debit_amount=Decimal(amount),
            credit_amount=ZERO,
            running_balance=None,
        )
    return Card51Row(
        business_date=date.fromisoformat(day),
        document=document,
        debit_account=counter,
        credit_account="51",
        debit_amount=ZERO,
        credit_amount=Decimal(amount),
        running_balance=None,
    )


def test_august_03_and_17_same_number_different_dates() -> None:
    """Номер 373 на разных датах не перекрёстно матчится (регрессия августа)."""
    banks = [
        _bank(0, "2026-08-03", "1080.00", number="373"),
        _bank(1, "2026-08-17", "1080.00", number="374"),
    ]
    cards = aggregate_card_rows(
        [
            _card_row("2026-08-03", "1080.00", "Doc 373 aug3", "62.02"),
            _card_row("2026-08-17", "1080.00", "Doc 374 aug17", "62.01"),
        ]
    )
    report = match_bank_to_card51(banks, cards)
    assert report.not_found_bank_indices == []
    assert report.matched_pair_count == 2


def test_order_independent_shuffle() -> None:
    banks = [
        _bank(0, "2026-09-01", "100.00", number="A"),
        _bank(1, "2026-09-02", "200.00", number="B"),
        _bank(2, "2026-09-03", "300.00", number="C"),
    ]
    cards = aggregate_card_rows(
        [
            _card_row("2026-09-01", "100.00", "A doc", "62.02"),
            _card_row("2026-09-02", "200.00", "B doc", "62.02"),
            _card_row("2026-09-03", "300.00", "C doc", "62.01"),
        ]
    )
    baseline = match_bank_to_card51(banks, cards)
    for seed in (1, 7, 99):
        random.seed(seed)
        shuffled = list(banks)
        random.shuffle(shuffled)
        reindexed = [
            BankMovement(i, b.direction, b.business_date, b.amount, b.document_number)
            for i, b in enumerate(shuffled)
        ]
        report = match_bank_to_card51(reindexed, cards)
        assert report.matched_pair_count == baseline.matched_pair_count
        assert report.not_found_bank_indices == []


def test_one_to_n_card_rows_single_aggregate() -> None:
    rows = [
        _card_row("2026-09-04", "700.00", "Split 42", "62.01"),
        _card_row("2026-09-04", "300.00", "Split 42", "62.02"),
    ]
    cards = aggregate_card_rows(rows)
    assert len(cards) == 1
    assert cards[0].source_row_count == 2
    banks = [_bank(0, "2026-09-04", "1000.00", number="42")]
    report = match_bank_to_card51(banks, cards)
    assert report.matched_pair_count == 1


def test_duplicate_amount_same_day_group_equivalent() -> None:
    banks = [
        _bank(0, "2026-09-07", "2000.00", number=""),
        _bank(1, "2026-09-07", "2000.00", number=""),
    ]
    cards = aggregate_card_rows(
        [
            _card_row("2026-09-07", "2000.00", "G1", "62.02"),
            _card_row("2026-09-07", "2000.00", "G2", "62.02"),
        ]
    )
    report = match_bank_to_card51(banks, cards)
    assert report.group_matched_equivalent_count == 1
    assert report.not_found_bank_indices == []


def test_mixed_sections_needs_confirmation() -> None:
    banks = [
        _bank(0, "2026-09-10", "5000.00", number=""),
        _bank(1, "2026-09-10", "5000.00", number=""),
    ]
    cards = aggregate_card_rows(
        [
            _card_row("2026-09-10", "5000.00", "Inv", "55.03"),
            _card_row("2026-09-10", "5000.00", "Op", "62.02"),
        ]
    )
    report = match_bank_to_card51(banks, cards)
    assert report.needs_confirmation_group_count == 1
    assert report.not_found_bank_indices == []


def test_daily_chain_break_detected() -> None:
    s1 = ClientBankDailySection(
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 1),
        account="51",
        opening=Decimal("100"),
        total_in=Decimal("0"),
        total_out=Decimal("0"),
        closing=Decimal("100"),
    )
    s2 = ClientBankDailySection(
        period_start=date(2026, 9, 2),
        period_end=date(2026, 9, 2),
        account="51",
        opening=Decimal("99"),
        total_in=Decimal("0"),
        total_out=Decimal("0"),
        closing=Decimal("99"),
    )
    errors = daily_chain_errors([s1, s2])
    assert errors
