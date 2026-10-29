"""FA-R03 · CLI проверки месяца (вне CI). Только числа и агрегаты.

Запуск:
    cd backend && python -m app.tools.fa_r03_check <папка> --month 2026-09

Читает образцы S1/S2/S3/S12 и печатает отчёт. В вывод не попадают названия
контрагентов, ФИО, номера счетов и тексты назначений: промахи правил
показываются обобщёнными шаблонами (цифры → #).
"""

from __future__ import annotations

import argparse
import re
import sys
import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.catalog.classification_packs.loader import load_pack, rule_priority
from app.domain.imports.clientbank import read_clientbank
from app.domain.imports.fa_r03.clientbank_daily import parse_clientbank_daily_sections
from app.domain.imports.fa_r03.reconcile import (
    Account51Totals,
    daily_chain_errors,
    totals_from_daily_sections,
)
from app.domain.imports.fa_r03.xls_reader import (
    Card51Row,
    Card51Sheet,
    Osv57Sheet,
    OsvSheet,
    XlsFormatError,
    read_card51,
    read_osv,
    read_osv_5703,
)
from app.domain.imports.rules import RuleView, matching_rule
from app.domain.money import money_str

PACK_SLUG = "ru-bank-clientbank"
PACK_VERSION = "1.0.0"
ZERO = Decimal("0.00")

# Эталонная трактовка корреспонденции счетов для сверки (не правила продукта).
INBOUND_SECTIONS = {
    "62.01": "operating",
    "62.02": "operating",
    "57.03": "operating",
    "90.01.1": "operating",
    "55.03": "investing",
    "91.01": "investing",
}
OUTBOUND_SECTIONS = {
    "60.01": "operating",
    "60.02": "operating",
    "70": "operating",
    "69.11": "operating",
    "68.90": "operating",
    "91.02": "operating",
    "55.03": "investing",
    "50.01": "technical",
}


@dataclass(frozen=True)
class MonthSamples:
    folder: Path
    s1: Path | None
    s2: Path | None
    s3: Path | None
    s12: Path | None


@dataclass(frozen=True)
class S1Document:
    direction: str
    business_date: date
    amount: Decimal
    document_number: str
    description: str
    counterparty_inn: str


@dataclass(frozen=True)
class CardAggregate:
    """Один документ 1С из карточки 51: сумма, корреспонденция, эталонная секция."""

    direction: str
    business_date: date
    amount: Decimal
    document: str
    counter_accounts: tuple[str, ...]
    section: str | None


def find_samples(folder: Path) -> MonthSamples:
    if not folder.is_dir():
        raise SystemExit(f"Папка не найдена: {folder}")

    def pick(prefix: str, suffix: str) -> Path | None:
        for item in sorted(folder.iterdir()):
            name = item.name.upper()
            if item.is_file() and name.startswith(prefix) and name.lower().endswith(suffix):
                return item
        return None

    return MonthSamples(
        folder=folder,
        s1=pick("S1_", ".txt"),
        s2=pick("S2_", ".xls"),
        s3=pick("S3_", ".xls"),
        s12=pick("S12_", ".xls"),
    )


def detect_encoding(raw: bytes) -> str:
    """UTF-8, если декодируется; иначе cp1251 (типовая выгрузка 1С на Windows)."""
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1251"


def load_s1(path: Path) -> tuple[str, list[S1Document], int]:
    raw = path.read_bytes()
    encoding = detect_encoding(raw)
    lines = read_clientbank(raw, encoding=encoding, max_rows=100_000, wallet_code="51")
    docs: list[S1Document] = []
    skipped = 0
    for line in lines:
        if line.errors or line.business_date is None or line.amount is None:
            skipped += 1
            continue
        docs.append(
            S1Document(
                direction=line.direction,
                business_date=line.business_date,
                amount=line.amount,
                document_number=str(line.document_number or "").strip(),
                description=line.description,
                counterparty_inn=line.counterparty_inn or "",
            )
        )
    return encoding, docs, skipped


def section_for_account(account: str, direction: str) -> str | None:
    table = INBOUND_SECTIONS if direction == "in" else OUTBOUND_SECTIONS
    return table.get(account.strip())


def aggregate_card(card: Card51Sheet) -> list[CardAggregate]:
    """Склеивает строки карточки в документы 1С и определяет секцию эталона."""
    buckets: dict[tuple[str, date, str], list[Card51Row]] = defaultdict(list)
    for row in card.rows:
        buckets[(row.direction, row.business_date, row.document.strip())].append(row)

    aggregates: list[CardAggregate] = []
    for (direction, business_date, document), rows in buckets.items():
        amount = sum((row.amount for row in rows), ZERO)
        accounts = tuple(row.counter_account for row in rows)
        sections = [section_for_account(acc, direction) for acc in accounts]
        known = [section for section in sections if section]
        section = max(set(known), key=known.count) if known else None
        aggregates.append(
            CardAggregate(
                direction=direction,
                business_date=business_date,
                amount=amount,
                document=document,
                counter_accounts=accounts,
                section=section,
            )
        )
    return aggregates


def pack_rule_views(slug: str = PACK_SLUG, version: str = PACK_VERSION) -> tuple[RuleView, ...]:
    """Правила набора в виде, который принимает продуктовый matcher (без БД)."""
    pack = load_pack(slug, version)
    views: list[RuleView] = []
    for index, spec in enumerate(pack.rules):
        views.append(
            RuleView(
                rule_id=uuid.UUID(int=index + 1),
                rule_version=1,
                priority=rule_priority(pack, spec),
                enabled=True,
                conditions=dict(spec.conditions),
                category_code=spec.category_code,
            )
        )
    return tuple(views)


def predict_section(rules: tuple[RuleView, ...], doc: S1Document) -> str:
    """Тот же матчер, что в продукте: первое включённое правило по приоритету."""
    matched = matching_rule(
        rules,
        description=doc.description,
        counterparty_inn=doc.counterparty_inn,
        direction=doc.direction,
        amount=doc.amount,
    )
    if matched is None or not matched.category_code:
        return "unknown"
    return matched.category_code


def template_description(text: str) -> str:
    """Обобщение назначения: цифры → #. Без названий, ФИО и ИНН."""
    without_digits = re.sub(r"\d+", "#", text or "")
    collapsed = re.sub(r"\s+", " ", without_digits).strip()
    return collapsed[:60] if collapsed else "—"


ACQUIRING_GROSS_RE = re.compile(r"СУММА\s*:\s*([\d\s]+[.,]\d{2})", re.IGNORECASE)
ACQUIRING_FEE_RE = re.compile(r"УСЛ\.?\s*БАНКА\s*:\s*([\d\s]+[.,]\d{2})", re.IGNORECASE)
# Суммы с копейками; даты вида 31.08.2026 сюда не попадают (после них ещё цифры).
AMOUNT_RE = re.compile(r"(?<![\d.])(\d[\d\s]*)[.,](\d{1,2})(?!\d|[.,]\d)")
# Целые суммы без копеек в назначениях эквайера: «, 17098,».
# Запрещены соседние цифры и дробная часть («.26»), но не запятая-разделитель.
WHOLE_AMOUNT_RE = re.compile(r"(?<![\d.,])(\d{4,8})(?!\d|[.]\d)")
ACQUIRING_HINTS = ("СУММА", "УСЛ", "В Т.Ч", "В ТЧ")


def _amounts_in(text: str) -> list[Decimal]:
    found: list[Decimal] = []
    for match in AMOUNT_RE.finditer(text):
        value = _parse_description_amount(f"{match.group(1)}.{match.group(2)}")
        if value is not None:
            found.append(value)
    for match in WHOLE_AMOUNT_RE.finditer(text):
        value = _parse_description_amount(match.group(1))
        if value is not None:
            found.append(value)
    return found


def parse_acquiring(description: str, net: Decimal | None = None) -> tuple[Decimal, Decimal] | None:
    """Валовая сумма и комиссия из назначения эквайрингового поступления.

    Форматы выписок различаются («…СУММА:7645.00,В Т.Ч.УСЛ.БАНКА:173.50» и
    «…, Сумма №…, 21833,94, … 644,17. В тч НДС»), поэтому разбор опирается на
    проверку: валовая − комиссия должна равняться фактически поступившей сумме.
    Возвращает (gross, fee) или None, если это не эквайринг.
    """
    text = description or ""
    if net is None:
        net = _net_from_text(text)
    if net is None:
        return None

    gross_match = ACQUIRING_GROSS_RE.search(text)
    fee_match = ACQUIRING_FEE_RE.search(text)
    if gross_match is not None and fee_match is not None:
        gross = _parse_description_amount(gross_match.group(1))
        fee = _parse_description_amount(fee_match.group(1))
        if gross is not None and fee is not None and gross - fee == net:
            return gross, fee

    upper = text.upper()
    if not any(hint in upper for hint in ACQUIRING_HINTS):
        return None
    amounts = _amounts_in(text)
    for gross in amounts:
        for fee in amounts:
            if gross > fee and gross - fee == net:
                return gross, fee
    return None


def _net_from_text(_text: str) -> Decimal | None:
    return None


def _parse_description_amount(raw: str) -> Decimal | None:
    text = raw.replace(" ", "").replace("\xa0", "").replace(",", ".")
    try:
        value = Decimal(text)
    except Exception:  # noqa: BLE001 - в назначении бывает мусор
        return None
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        return None
    return value.quantize(Decimal("0.01"))


def _money(value: Decimal) -> str:
    return money_str(value)


def _header(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def _pct(part: Decimal, total: Decimal) -> str:
    if total == ZERO:
        return "н/д"
    return f"{part / total * 100:.2f} %"


def match_aggregates(docs: Sequence[S1Document], aggregates: Sequence[CardAggregate]) -> list:
    """Пары «документ S1 ↔ документ карточки» по направлению, дате и сумме."""
    pool = list(aggregates)
    pairs: list[tuple[S1Document, CardAggregate]] = []
    for doc in docs:
        found: CardAggregate | None = None
        for index, item in enumerate(pool):
            if (
                item.direction == doc.direction
                and item.business_date == doc.business_date
                and _money(item.amount) == _money(doc.amount)
            ):
                found = item
                pool.pop(index)
                break
        if found is not None:
            pairs.append((doc, found))
    return pairs


def match_by_document_number(
    docs: Sequence[S1Document], aggregates: Sequence[CardAggregate]
) -> tuple[int, int, int]:
    """Сопоставление по номеру документа 1С внутри названия документа карточки.

    Возвращает: сколько документов S1 нашли ровно одну пару, сколько пары не нашли,
    сколько нашли несколько кандидатов (неоднозначность).
    """
    unique = 0
    missing = 0
    ambiguous = 0
    for doc in docs:
        number = doc.document_number.strip()
        if not number:
            missing += 1
            continue
        candidates = [
            item
            for item in aggregates
            if number in item.document
            and item.direction == doc.direction
            and _money(item.amount) == _money(doc.amount)
        ]
        if len(candidates) == 1:
            unique += 1
        elif not candidates:
            missing += 1
        else:
            ambiguous += 1
    return unique, missing, ambiguous


def _looks_like_acquiring(description: str) -> bool:
    upper = (description or "").upper()
    return any(hint in upper for hint in ACQUIRING_HINTS)


def _acquiring_doc(doc: S1Document, card: Card51Sheet) -> bool:
    """Поступление проведено через 57.03 (эквайринг) — по карточке 51."""
    for row in card.rows:
        if (
            row.direction == "in"
            and row.counter_account == "57.03"
            and row.business_date == doc.business_date
            and row.amount == doc.amount
        ):
            return True
    return False


def run(folder: Path, month_label: str) -> int:
    try:
        year, month = (int(part) for part in month_label.split("-"))
    except ValueError:
        raise SystemExit("--month должен быть в формате ГГГГ-ММ") from None

    samples = find_samples(folder)
    print(f"Проверка месяца {year:04d}-{month:02d}")
    print(f"Папка образцов: {samples.folder}")
    for label, path in (
        ("S1", samples.s1),
        ("S2", samples.s2),
        ("S3", samples.s3),
        ("S12", samples.s12),
    ):
        print(f"{label}: {path.name if path else 'нет'}")

    if samples.s1 is None:
        print("\nБез S1 проверка невозможна.")
        return 2

    _header("1. S1 · выписка по счёту 51")
    encoding, docs, skipped = load_s1(samples.s1)
    total_in = sum((doc.amount for doc in docs if doc.direction == "in"), ZERO)
    total_out = sum((doc.amount for doc in docs if doc.direction == "out"), ZERO)
    print(f"кодировка: {encoding}")
    print(f"документов: {len(docs)} (с ошибками разбора: {skipped})")
    print(f"поступлений: {sum(1 for doc in docs if doc.direction == 'in')} на {_money(total_in)}")
    print(f"списаний: {sum(1 for doc in docs if doc.direction == 'out')} на {_money(total_out)}")

    sections = parse_clientbank_daily_sections(samples.s1.read_bytes(), encoding=encoding)
    chain_errors = daily_chain_errors(sections)
    daily = totals_from_daily_sections(sections)
    print(f"секций по суткам: {len(sections)}")
    print(f"остаток: {_money(daily.opening)} → {_money(daily.closing)}")
    print(f"ошибок цепочки остатков: {len(chain_errors)}")

    _header("2. Сверка по счёту 51: S1 = S2 = S3 (допуск 0,00)")
    card: Card51Sheet | None = None
    if samples.s2 is not None:
        try:
            card = read_card51(samples.s2)
            print(
                f"S2: строк {len(card.rows)}, Дт {_money(card.turnover_debit or ZERO)}"
                f" Кт {_money(card.turnover_credit or ZERO)}"
            )
        except XlsFormatError as exc:
            print(f"S2 не прочитан: {exc}")
    else:
        print("S2: нет файла")

    osv: OsvSheet | None = None
    totals_s3: Account51Totals | None = None
    if samples.s3 is not None:
        try:
            osv = read_osv(samples.s3)
            row = osv.by_code("51")
            if row is not None:
                totals_s3 = Account51Totals(
                    opening=row.opening_debit - row.opening_credit,
                    total_in=row.turnover_debit,
                    total_out=row.turnover_credit,
                    closing=row.closing_debit - row.closing_credit,
                )
                print(
                    f"S3: счёт 51 Дт {_money(row.turnover_debit)} Кт {_money(row.turnover_credit)}"
                )
            else:
                print("S3: в ОСВ нет счёта 51")
        except XlsFormatError as exc:
            print(f"S3 не прочитан: {exc}")
    else:
        print("S3: нет файла")

    s1_totals = Account51Totals(
        opening=daily.opening,
        total_in=total_in,
        total_out=total_out,
        closing=daily.closing,
    )
    compared: list[tuple[str, Account51Totals]] = [("S1", s1_totals)]
    if card is not None:
        compared.append(
            (
                "S2",
                Account51Totals(
                    opening=card.opening_balance or ZERO,
                    total_in=card.turnover_debit or ZERO,
                    total_out=card.turnover_credit or ZERO,
                    closing=card.closing_balance or ZERO,
                ),
            )
        )
    if totals_s3 is not None:
        compared.append(("S3", totals_s3))

    if len(compared) < 2:
        print("итог: недостаточно источников (нужен S2 или S3)")
    else:
        values = [item for _label, item in compared]
        same = True
        for key in ("opening", "total_in", "total_out", "closing"):
            base = values[0]
            for other in values[1:]:
                if abs(getattr(base, key) - getattr(other, key)) > ZERO:
                    same = False
        names = " = ".join(label for label, _item in compared)
        print(f"итог {names}: {'совпало' if same else 'РАСХОЖДЕНИЕ'}")
        if not same:
            for label, item in compared:
                print(
                    f"  {label}: начало {_money(item.opening)} Дт {_money(item.total_in)}"
                    f" Кт {_money(item.total_out)} конец {_money(item.closing)}"
                )

    _header("3. Сопоставление S1 ↔ S2 по номеру документа 1С")
    aggregates = aggregate_card(card) if card is not None else []
    pairs = match_aggregates(docs, aggregates) if aggregates else []
    if card is None:
        print("пропущено: нет S2")
    else:
        unique, missing, ambiguous = match_by_document_number(docs, aggregates)
        print(f"документов S1: {len(docs)}, агрегатов S2: {len(aggregates)}")
        print(f"номер документа 1С найден в названии S2: {unique}")
        print(f"не найден: {missing}")
        print(f"неоднозначно (несколько кандидатов): {ambiguous}")
        print(f"пар по направлению + дате + сумме: {len(pairs)}")
        multi = [item for item in aggregates if len(item.counter_accounts) > 1]
        print(f"документов из нескольких строк карточки: {len(multi)}")

    _header("4. Эквайринг по счёту 57.03 (S12)")
    s12: Osv57Sheet | None = None
    if samples.s12 is None:
        print("пропущено: нет S12")
    else:
        try:
            s12 = read_osv_5703(samples.s12)
        except XlsFormatError as exc:
            print(f"S12 не прочитан: {exc}")
    if s12 is not None:
        daily57 = s12.daily_turnovers()
        print(f"контрагентов: {len(s12.root.children)}, дней с оборотами: {len(daily57)}")
        print(
            f"оборот 57.03 Дт {_money(s12.root.turnover_debit)}"
            f" Кт {_money(s12.root.turnover_credit)}"
        )
        print(f"итого по листу: {_money(s12.total_debit)}")

        # Валовая сумма и комиссия берутся из назначений S1 по дням.
        gross_by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)
        fee_by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)
        acquiring_docs = 0
        acquiring_skipped = 0
        for doc in docs:
            if doc.direction != "in":
                continue
            if card is not None and not _acquiring_doc(doc, card):
                continue
            parsed = parse_acquiring(doc.description, net=doc.amount)
            if parsed is None:
                if not _looks_like_acquiring(doc.description):
                    continue
                acquiring_skipped += 1
                continue
            gross, fee = parsed
            acquiring_docs += 1
            gross_by_day[doc.business_date] += gross
            fee_by_day[doc.business_date] += fee

        print(f"эквайринговых поступлений в S1: {acquiring_docs}")
        if acquiring_skipped:
            print(f"не разобрано назначений: {acquiring_skipped}")
        print(f"валовая по назначениям: {_money(sum(gross_by_day.values(), ZERO))}")
        print(f"комиссия по назначениям: {_money(sum(fee_by_day.values(), ZERO))}")
        print(
            f"валовая − комиссия: "
            f"{_money(sum(gross_by_day.values(), ZERO) - sum(fee_by_day.values(), ZERO))}"
        )

        if acquiring_docs == 0:
            print("сверка по дням пропущена: в назначениях нет валовых сумм эквайринга")
        else:
            mismatch_days = [
                day
                for day, amount in sorted(daily57.items())
                if gross_by_day.get(day, ZERO) != amount
            ]
            print(f"дней с расхождением «валовая = оборот 57.03»: {len(mismatch_days)}")

        if card is not None:
            by_day: dict[date, Decimal] = defaultdict(lambda: ZERO)
            for card_row in card.rows:
                if card_row.direction == "in" and card_row.counter_account == "57.03":
                    by_day[card_row.business_date] += card_row.amount
            print(f"поступлений на 51 через 57.03 в S2: {_money(sum(by_day.values(), ZERO))}")
            if acquiring_docs:
                net_gross = sum(gross_by_day.values(), ZERO) - sum(fee_by_day.values(), ZERO)
                net_card = sum(by_day.values(), ZERO)
                print(f"разница «валовая − комиссия» vs S2: {_money(net_gross - net_card)}")
                print(
                    "дней с расхождением S12 vs S2: "
                    f"{_money(ZERO) if not mismatch_days else len(mismatch_days)}"
                )

    _header("5. Комиссии и эквайринг на счёте 91.02")
    if osv is None or card is None:
        print("пропущено: нужны S2 и S3")
    else:
        row9102 = osv.by_code("91.02")
        if row9102 is None:
            print("в ОСВ нет счёта 91.02")
        else:
            fees = sum(
                (
                    row.amount
                    for row in card.rows
                    if row.direction == "out" and row.counter_account == "91.02"
                ),
                ZERO,
            )
            acquiring_fee_total = sum(fee_by_day.values(), ZERO) if s12 is not None else None
            print(f"оборот Дт 91.02 в ОСВ: {_money(row9102.turnover_debit)}")
            print(f"комиссии банка (списания на 91.02 в S2): {_money(fees)}")
            if acquiring_fee_total is None:
                print("комиссия эквайринга: н/д (нет S12)")
                print(f"разница только по комиссиям банка: {_money(row9102.turnover_debit - fees)}")
            else:
                print(f"комиссия эквайринга (из S12/S1): {_money(acquiring_fee_total)}")
                expected = fees + acquiring_fee_total
                print(f"ожидается по 91.02: {_money(expected)}")
                print(f"разница: {_money(row9102.turnover_debit - expected)}")

    _header("6. Точность набора правил v1 против эталона S2")
    if not pairs:
        print("пропущено: нет сопоставленных пар S1 ↔ S2")
    else:
        rules = pack_rule_views()
        matrix_sum: dict[tuple[str, str], Decimal] = defaultdict(lambda: ZERO)
        matrix_cnt: dict[tuple[str, str], int] = defaultdict(int)
        errors: list[tuple[str, str, str, str]] = []
        total_sum = ZERO
        total_cnt = 0
        correct_sum = ZERO
        correct_cnt = 0
        unlabeled = 0

        for doc, agg in pairs:
            if agg.section is None:
                unlabeled += 1
                continue
            predicted = predict_section(rules, doc)
            total_sum += doc.amount
            total_cnt += 1
            matrix_sum[(agg.section, predicted)] += doc.amount
            matrix_cnt[(agg.section, predicted)] += 1
            if agg.section == predicted:
                correct_sum += doc.amount
                correct_cnt += 1
            else:
                errors.append(
                    (
                        agg.section,
                        predicted,
                        template_description(doc.description),
                        _money(doc.amount),
                    )
                )

        print(f"документов с эталонной секцией: {total_cnt} (без метки: {unlabeled})")
        if total_cnt:
            print(f"точность по сумме: {_pct(correct_sum, total_sum)}")
            print(f"точность по количеству: {_pct(Decimal(correct_cnt), Decimal(total_cnt))}")
            print("оговорка: обучающая выборка, не доказательство качества")
        print("матрица «эталон → правило», рубли и штуки:")
        for (ref, predicted), amount in sorted(matrix_sum.items(), key=lambda item: -item[1]):
            print(
                f"  {ref:10s} → {predicted:10s} "
                f"{_money(amount):>16s}  {matrix_cnt[(ref, predicted)]}"
            )
        if errors:
            print(f"промахи: {len(errors)} (шаблоны без цифр и названий)")
            for ref, predicted, template, miss_amount in errors[:20]:
                print(f"  {ref} → {predicted}  {miss_amount}  «{template}»")
        else:
            print("промахов нет")

    _header("7. Ожидаемые образцы")
    print("S11 (журнал реализаций): ожидается образец")
    print("S9/S10 (счёт 62): ожидается образец")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка месяца FA-R03: S1/S2/S3/S12 и точность набора правил.",
    )
    parser.add_argument("folder", type=Path, help="папка с образцами S1_*/S2_*/S3_*/S12_*")
    parser.add_argument("--month", required=True, help="месяц в формате ГГГГ-ММ")
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(args.folder, args.month)


if __name__ == "__main__":
    sys.exit(main())
