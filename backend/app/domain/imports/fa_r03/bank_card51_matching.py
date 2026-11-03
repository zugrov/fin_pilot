"""Сопоставление S1 ↔ карточка 51: ступень 1 + группы (FA-R03.2 MVP)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from app.domain.imports.fa_r03.cash_flow_sections import section_for_account
from app.domain.money import money

ZERO = Decimal("0.00")

GroupKind = Literal[
    "matched_pair",
    "group_matched_equivalent",
    "needs_confirmation",
    "not_found",
]
Stage1Kind = Literal["matched_pair", "ambiguous"]


@dataclass(frozen=True)
class BankMovement:
    """Документ банковской выписки (без текста назначения)."""

    index: int
    direction: str
    business_date: date
    amount: Decimal
    document_number: str


@dataclass(frozen=True)
class CardMovementAggregate:
    """Агрегат карточки 51 (1→N строк с одним названием документа)."""

    index: int
    direction: str
    business_date: date
    amount: Decimal
    document_title: str
    counter_accounts: tuple[str, ...]
    source_row_count: int

    @property
    def primary_section(self) -> str | None:
        sections = [section_for_account(acc, self.direction) for acc in self.counter_accounts]
        known = [item for item in sections if item]
        if not known:
            return None
        return max(set(known), key=known.count)


@dataclass(frozen=True)
class AmountGroupKey:
    direction: str
    business_date: date
    amount: Decimal


@dataclass
class Stage1Match:
    bank_index: int
    card_index: int
    kind: Stage1Kind


@dataclass
class GroupMatchResult:
    key: AmountGroupKey
    bank_indices: tuple[int, ...]
    card_indices: tuple[int, ...]
    kind: GroupKind


@dataclass
class BankCardMatchReport:
    bank_count: int
    card_aggregate_count: int
    stage1_pairs: list[Stage1Match] = field(default_factory=list)
    groups: list[GroupMatchResult] = field(default_factory=list)
    not_found_bank_indices: list[int] = field(default_factory=list)
    not_found_card_indices: list[int] = field(default_factory=list)

    @property
    def matched_pair_count(self) -> int:
        return sum(1 for item in self.stage1_pairs if item.kind == "matched_pair") + sum(
            1 for g in self.groups if g.kind == "matched_pair"
        )

    @property
    def group_matched_equivalent_count(self) -> int:
        return sum(1 for g in self.groups if g.kind == "group_matched_equivalent")

    @property
    def needs_confirmation_group_count(self) -> int:
        return sum(1 for g in self.groups if g.kind == "needs_confirmation")

    @property
    def ambiguous_stage1_count(self) -> int:
        return sum(1 for item in self.stage1_pairs if item.kind == "ambiguous")


def aggregate_card_rows(rows: list) -> list[CardMovementAggregate]:
    """Склейка строк карточки по (direction, date, document title)."""
    buckets: dict[tuple[str, date, str], list] = defaultdict(list)
    for row in rows:
        title = (row.document or "").strip()
        key = (row.direction, row.business_date, title)
        buckets[key].append(row)

    aggregates: list[CardMovementAggregate] = []
    index = 0
    for (direction, business_date, title), group in buckets.items():
        amount = money(sum((item.amount for item in group), ZERO))
        accounts = tuple(item.counter_account for item in group)
        aggregates.append(
            CardMovementAggregate(
                index=index,
                direction=direction,
                business_date=business_date,
                amount=amount,
                document_title=title,
                counter_accounts=accounts,
                source_row_count=len(group),
            )
        )
        index += 1
    return aggregates


def _group_key(bank: BankMovement) -> AmountGroupKey:
    return AmountGroupKey(bank.direction, bank.business_date, money(bank.amount))


def _stage1_candidates(
    bank: BankMovement,
    card: CardMovementAggregate,
) -> bool:
    number = bank.document_number.strip()
    if not number:
        return False
    return (
        number in card.document_title
        and bank.direction == card.direction
        and bank.business_date == card.business_date
        and money(bank.amount) == money(card.amount)
    )


def _classify_multi_group(
    cards: list[CardMovementAggregate],
) -> Literal["group_matched_equivalent", "needs_confirmation"]:
    sections = {item.primary_section for item in cards}
    corr_sets = {item.counter_accounts for item in cards}
    known_sections = {item for item in sections if item is not None}
    if len(known_sections) == 1 and len(sections) == 1:
        return "group_matched_equivalent"
    if len(corr_sets) == 1:
        return "group_matched_equivalent"
    return "needs_confirmation"


def _section_amounts(cards: list[CardMovementAggregate]) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for card in cards:
        section = card.primary_section
        if section is None:
            continue
        totals[section] = money(totals[section] + money(card.amount))
    return dict(totals)


def match_bank_to_card51(
    bank_docs: list[BankMovement],
    card_aggregates: list[CardMovementAggregate],
) -> BankCardMatchReport:
    """Сопоставление, не зависящее от порядка документов S1."""
    report = BankCardMatchReport(
        bank_count=len(bank_docs),
        card_aggregate_count=len(card_aggregates),
    )
    available_bank = {doc.index for doc in bank_docs}
    available_card = {doc.index for doc in card_aggregates}
    bank_by_index = {doc.index: doc for doc in bank_docs}
    card_by_index = {doc.index: doc for doc in card_aggregates}

    for bank in sorted(bank_docs, key=lambda item: item.index):
        if bank.index not in available_bank:
            continue
        number = bank.document_number.strip()
        if not number:
            continue
        candidates = [
            card
            for card in card_aggregates
            if card.index in available_card and _stage1_candidates(bank, card)
        ]
        if len(candidates) == 1:
            card = candidates[0]
            report.stage1_pairs.append(
                Stage1Match(bank.index, card.index, "matched_pair")
            )
            available_bank.remove(bank.index)
            available_card.remove(card.index)
        elif len(candidates) > 1:
            report.stage1_pairs.append(
                Stage1Match(bank.index, candidates[0].index, "ambiguous")
            )

    groups: dict[AmountGroupKey, tuple[list[int], list[int]]] = defaultdict(
        lambda: ([], [])
    )
    for index in sorted(available_bank):
        bank = bank_by_index[index]
        groups[_group_key(bank)][0].append(index)
    for index in sorted(available_card):
        card = card_by_index[index]
        key = AmountGroupKey(card.direction, card.business_date, money(card.amount))
        groups[key][1].append(index)

    def _sort_key(item: AmountGroupKey) -> tuple:
        return (item.business_date, item.direction, item.amount)

    for key in sorted(groups.keys(), key=_sort_key):
        bank_indices, card_indices = groups[key]
        bank_list = [bank_by_index[i] for i in bank_indices]
        card_list = [card_by_index[i] for i in card_indices]
        if not bank_list and not card_list:
            continue
        if len(bank_list) != len(card_list):
            report.not_found_bank_indices.extend(bank_indices)
            report.not_found_card_indices.extend(card_indices)
            report.groups.append(
                GroupMatchResult(
                    key=key,
                    bank_indices=tuple(bank_indices),
                    card_indices=tuple(card_indices),
                    kind="not_found",
                )
            )
            continue

        if len(bank_list) == 1:
            report.groups.append(
                GroupMatchResult(
                    key=key,
                    bank_indices=tuple(bank_indices),
                    card_indices=tuple(card_indices),
                    kind="matched_pair",
                )
            )
            continue

        section_totals = _section_amounts(card_list)
        if len(section_totals) > 1:
            total_check = money(sum(section_totals.values(), ZERO))
            expected = money(key.amount * len(bank_list))
            if total_check != expected:
                report.not_found_bank_indices.extend(bank_indices)
                report.not_found_card_indices.extend(card_indices)
                report.groups.append(
                    GroupMatchResult(
                        key=key,
                        bank_indices=tuple(bank_indices),
                        card_indices=tuple(card_indices),
                        kind="not_found",
                    )
                )
                continue

        kind = _classify_multi_group(card_list)
        report.groups.append(
            GroupMatchResult(
                key=key,
                bank_indices=tuple(bank_indices),
                card_indices=tuple(card_indices),
                kind=kind,
            )
        )

    return report
