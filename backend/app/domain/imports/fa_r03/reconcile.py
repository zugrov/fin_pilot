"""FA-R03.2b: сверка S1/S2/S3 как чистые функции (Decimal, допуск 0,00)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.domain.imports.fa_r03.clientbank_daily import ClientBankDailySection
from app.domain.money import money

ZERO = Decimal("0.00")


class CardRowLike(Protocol):
    """Минимум, который даёт чтение .xls (FA-R03.2c)."""

    business_date: date
    document: str
    amount: Decimal

    @property
    def direction(self) -> str: ...


class StatementLike(Protocol):
    direction: str
    business_date: date
    amount: Decimal
    document_number: str | None


@dataclass(frozen=True)
class Account51Totals:
    opening: Decimal
    total_in: Decimal
    total_out: Decimal
    closing: Decimal


@dataclass(frozen=True)
class StatementDocument:
    direction: str
    business_date: date
    amount: Decimal
    document_number: str


@dataclass(frozen=True)
class Card51Row:
    direction: str
    business_date: date
    amount: Decimal
    document_number: str | None = None


@dataclass(frozen=True)
class AggregatedCardDocument:
    direction: str
    business_date: date
    amount: Decimal
    document_number: str | None
    matched_without_doc_number: bool = False
    source_row_count: int = 1


@dataclass
class DocumentMatchResult:
    matched: list[tuple[StatementDocument, AggregatedCardDocument]] = field(default_factory=list)
    unmatched_statement: list[StatementDocument] = field(default_factory=list)
    unmatched_card: list[AggregatedCardDocument] = field(default_factory=list)


def daily_balance_formula_ok(section: ClientBankDailySection) -> bool:
    expected = money(section.opening + section.total_in - section.total_out)
    return money(section.closing) == expected


def daily_chain_errors(
    sections: list[ClientBankDailySection],
    *,
    account: str | None = None,
) -> list[str]:
    filtered = sections
    if account is not None:
        filtered = [item for item in sections if item.account == account]
    ordered = sorted(filtered, key=lambda item: (item.period_start, item.period_end))
    errors: list[str] = []
    for index, section in enumerate(ordered):
        if not daily_balance_formula_ok(section):
            errors.append(
                f"formula:{section.period_start.isoformat()}:"
                f"{section.opening}+{section.total_in}-{section.total_out}!={section.closing}"
            )
        if index + 1 >= len(ordered):
            continue
        nxt = ordered[index + 1]
        if money(section.closing) != money(nxt.opening):
            errors.append(
                f"chain:{section.period_end.isoformat()}->{nxt.period_start.isoformat()}:"
                f"{section.closing}!={nxt.opening}"
            )
    return errors


def totals_from_daily_sections(
    sections: list[ClientBankDailySection],
    *,
    account: str | None = None,
) -> Account51Totals:
    filtered = sections
    if account is not None:
        filtered = [item for item in sections if item.account == account]
    if not filtered:
        return Account51Totals(ZERO, ZERO, ZERO, ZERO)
    ordered = sorted(filtered, key=lambda item: (item.period_start, item.period_end))
    total_in = money(sum((item.total_in for item in ordered), ZERO))
    total_out = money(sum((item.total_out for item in ordered), ZERO))
    return Account51Totals(
        opening=money(ordered[0].opening),
        total_in=total_in,
        total_out=total_out,
        closing=money(ordered[-1].closing),
    )


def account51_totals_equal(
    first: Account51Totals,
    second: Account51Totals,
    third: Account51Totals | None = None,
    *,
    tolerance: Decimal = ZERO,
) -> bool:
    items = [first, second] if third is None else [first, second, third]
    keys = ("opening", "total_in", "total_out", "closing")
    for key in keys:
        values = [money(getattr(item, key)) for item in items]
        if not _all_within(values, tolerance):
            return False
    return True


def aggregate_card_rows(rows: list[Card51Row]) -> list[AggregatedCardDocument]:
    buckets: dict[tuple[str, date, str | None, bool], list[Card51Row]] = {}
    for row in rows:
        number_raw = (row.document_number or "").strip()
        has_number = bool(number_raw)
        doc_key: str | None = number_raw if has_number else None
        flag = not has_number
        key = (row.direction, row.business_date, doc_key, flag)
        buckets.setdefault(key, []).append(row)
    aggregated: list[AggregatedCardDocument] = []
    for (direction, business_date, doc_number, without_number), group in buckets.items():
        amount = money(sum((item.amount for item in group), ZERO))
        aggregated.append(
            AggregatedCardDocument(
                direction=direction,
                business_date=business_date,
                amount=amount,
                document_number=doc_number,
                matched_without_doc_number=without_number,
                source_row_count=len(group),
            )
        )
    return aggregated


def _statement_key(doc: StatementDocument) -> tuple[str, date, Decimal, str]:
    return (doc.direction, doc.business_date, money(doc.amount), doc.document_number.strip())


def _card_match_key(doc: AggregatedCardDocument) -> tuple[str, date, Decimal, str]:
    number = (doc.document_number or "").strip()
    return (doc.direction, doc.business_date, money(doc.amount), number)


def match_statement_to_card(
    statement_docs: list[StatementDocument],
    card_rows: list[Card51Row],
) -> DocumentMatchResult:
    card_docs = aggregate_card_rows(card_rows)
    card_pool = list(card_docs)
    result = DocumentMatchResult()
    for stmt in statement_docs:
        key = _statement_key(stmt)
        found: AggregatedCardDocument | None = None
        for index, card in enumerate(card_pool):
            if card.matched_without_doc_number:
                if (
                    card.direction == stmt.direction
                    and card.business_date == stmt.business_date
                    and money(card.amount) == money(stmt.amount)
                ):
                    found = card
                    card_pool.pop(index)
                    break
                continue
            if _card_match_key(card) == key:
                found = card
                card_pool.pop(index)
                break
        if found is None:
            result.unmatched_statement.append(stmt)
        else:
            result.matched.append((stmt, found))
    result.unmatched_card = card_pool
    return result


def _all_within(values: list[Decimal], tolerance: Decimal) -> bool:
    if not values:
        return True
    anchor = values[0]
    for item in values[1:]:
        if abs(money(item) - money(anchor)) > tolerance:
            return False
    return True


def card51_rows_to_reconcile(rows: list[CardRowLike]) -> list[Card51Row]:
    """Мост: строки карточки 51 → тип сверки (номер документа = название документа 1С)."""
    return [
        Card51Row(
            direction=row.direction,
            business_date=row.business_date,
            amount=money(row.amount),
            document_number=(row.document or "").strip() or None,
        )
        for row in rows
    ]


def statement_documents_from_s1(docs: list[StatementLike]) -> list[StatementDocument]:
    """Мост: разобранные документы S1 → тип сверки."""
    return [
        StatementDocument(
            direction=doc.direction,
            business_date=doc.business_date,
            amount=money(doc.amount),
            document_number=str(doc.document_number or "").strip(),
        )
        for doc in docs
    ]
