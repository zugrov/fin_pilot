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
from app.domain.imports.fa_r03.osv_month import (
    OsvCounterpartySheet,
    OsvSingleAccountSheet,
    carry_forward_union_breaks,
    closing_balance_sides,
    counterparty_turnover_consistent,
    daily_mismatch_days,
    osv_totals_mismatch,
    s1_days_without_osv_daily,
)
from app.domain.imports.fa_r03.osv_s3 import (
    first_level_totals,
    month_carry_breaks,
    read_osv_grand_total,
    totals_equal,
)
from app.domain.imports.fa_r03.reconcile import (
    Account51Totals,
    daily_chain_errors,
    totals_from_daily_sections,
)
from app.domain.imports.fa_r03.xls_reader import (
    Card51Row,
    Card51Sheet,
    Osv57Sheet,
    OsvRow,
    OsvSheet,
    XlsFormatError,
    read_card51,
    read_osv,
    read_osv_5703,
    read_osv_counterparties,
    read_osv_single_account,
)
from app.domain.imports.rules import RuleView, matching_rule
from app.domain.money import money, money_str

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
    s9: Path | None
    s9a: Path | None
    s9b: Path | None
    s12: Path | None
    s13: Path | None


DEPOSIT_PLACEMENT = ("РАЗМЕЩЕНИЕ ВКЛАД", "РАЗМЕЩЕНИЕ ДЕПОЗ", "ВО ВКЛАД", "НА ДЕПОЗ")
DEPOSIT_RETURN = ("ВОЗВРАТ ДЕПОЗИТ", "ВОЗВРАТ ВКЛАД")
DEPOSIT_INTEREST = ("ПРОЦЕНТОВ ПО ДЕПОЗ",)


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
        s9=pick("S9_", ".xls"),
        s9a=pick("S9A_", ".xls"),
        s9b=pick("S9B_", ".xls"),
        s12=pick("S12_", ".xls"),
        s13=pick("S13_", ".xls"),
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


def s1_document_kind_counts(content: bytes, encoding: str) -> dict[str, int]:
    """Считает типы СекцияДокумент= без вывода текстов платежей."""
    text = content.decode(encoding)
    counts: dict[str, int] = defaultdict(int)
    for line in text.splitlines():
        if line.startswith("СекцияДокумент="):
            counts[line.split("=", 1)[1].strip()] += 1
    return dict(counts)


def deposit_operation_bucket(description: str) -> str | None:
    upper = (description or "").upper()
    if any(marker in upper for marker in DEPOSIT_PLACEMENT):
        return "placement"
    if any(marker in upper for marker in DEPOSIT_RETURN):
        return "return"
    if any(marker in upper for marker in DEPOSIT_INTEREST):
        return "interest"
    return None


def report_pack_coverage(
    docs: Sequence[S1Document],
    rules: tuple[RuleView, ...],
) -> None:
    """Доля документов с правилом набора v1 и шаблоны непокрытых (без S2)."""
    matched_cnt = 0
    matched_sum = ZERO
    unknown_cnt = 0
    unknown_sum = ZERO
    templates: dict[str, int] = defaultdict(int)
    for doc in docs:
        predicted = predict_section(rules, doc)
        if predicted == "unknown":
            unknown_cnt += 1
            unknown_sum += doc.amount
            templates[template_description(doc.description)] += 1
        else:
            matched_cnt += 1
            matched_sum += doc.amount
    total_cnt = matched_cnt + unknown_cnt
    total_sum = matched_sum + unknown_sum
    cnt_pct = _pct(Decimal(matched_cnt), Decimal(total_cnt))
    print(f"документов с правилом: {matched_cnt} ({cnt_pct})")
    print(f"сумма с правилом: {_money(matched_sum)} ({_pct(matched_sum, total_sum)})")
    print(f"без правила: {unknown_cnt} на {_money(unknown_sum)}")
    print("точность не оценена: нет S2")
    if templates:
        print("шаблоны непокрытых (цифры → #):")
        for template, count in sorted(templates.items(), key=lambda item: -item[1])[:20]:
            print(f"  {count} × «{template}»")


def report_deposit_investing(docs: Sequence[S1Document], rules: tuple[RuleView, ...]) -> None:
    """Депозитные операции месяца: все должны классифицироваться как investing."""
    buckets: dict[str, int] = defaultdict(int)
    not_investing = 0
    for doc in docs:
        bucket = deposit_operation_bucket(doc.description)
        if bucket is None:
            continue
        buckets[bucket] += 1
        if predict_section(rules, doc) != "investing":
            not_investing += 1
    print(
        f"депозитные операции: размещение {buckets['placement']}, "
        f"возврат {buckets['return']}, проценты {buckets['interest']}"
    )
    print(f"не investing по правилам: {not_investing}")


def print_s13_reconcile(
    s13: OsvSingleAccountSheet,
    sections: list,
    s1_totals: Account51Totals,
) -> None:
    bad_days = daily_mismatch_days(s13.daily, sections)
    missing_osv = s1_days_without_osv_daily(s13.daily, sections)
    totals_bad = osv_totals_mismatch(
        s13,
        (s1_totals.opening, s1_totals.total_in, s1_totals.total_out, s1_totals.closing),
    )
    print(f"дней с оборотами в S13: {len(s13.daily)} (секций S1: {len(sections)})")
    print(f"дней S1 без строки S13: {len(missing_osv)}")
    print(f"дней с расхождением S13 ↔ S1: {len(bad_days)}")
    print(f"итог S13 ↔ S1: {'РАСХОЖДЕНИЕ' if totals_bad else 'совпало'}")


def deposit_flows_from_s1(docs: Sequence[S1Document]) -> tuple[Decimal, Decimal, Decimal]:
    """Размещение (исход), возврат и проценты (вход) по маркерам в назначении."""
    placed = ZERO
    returned = ZERO
    interest = ZERO
    for doc in docs:
        bucket = deposit_operation_bucket(doc.description)
        if bucket == "placement" and doc.direction == "out":
            placed += doc.amount
        elif bucket == "return" and doc.direction == "in":
            returned += doc.amount
        elif bucket == "interest" and doc.direction == "in":
            interest += doc.amount
    return money(placed), money(returned), money(interest)


def _osv_net(row: OsvRow) -> Decimal:
    return money(row.closing_debit - row.closing_credit)


def _osv_opening_net(row: OsvRow) -> Decimal:
    return money(row.opening_debit - row.opening_credit)


def _compare_money(label: str, left: Decimal, right: Decimal) -> None:
    diff = money(left - right)
    status = "совпало" if diff == ZERO else f"РАСХОЖДЕНИЕ ({_money(diff)})"
    print(f"{label}: {_money(left)} vs {_money(right)} — {status}")


def print_s3_full_osv(
    path: Path,
    *,
    s1_totals: Account51Totals | None,
    s13: OsvSingleAccountSheet | None,
    s12_gross: Decimal | None,
    s9_closing: Decimal | None,
    s9a_closing: Decimal | None,
    s9b_closing: Decimal | None,
    docs: Sequence[S1Document],
    next_s3: Path | None,
    acquiring_fee: Decimal | None,
) -> OsvSheet | None:
    try:
        sheet = read_osv(path)
        grand = read_osv_grand_total(path)
        level1 = first_level_totals(sheet)
    except XlsFormatError as exc:
        print(f"S3 не прочитан: {exc}")
        return None

    print(
        f"итог «Итого»: начало Дт/Кт {_money(grand.opening_debit)}/"
        f"{_money(grand.opening_credit)}; "
        f"оборот {_money(grand.turnover_debit)}/{_money(grand.turnover_credit)}; "
        f"конец {_money(grand.closing_debit)}/{_money(grand.closing_credit)}"
    )
    balanced = grand.balanced_opening() and grand.balanced_turnover() and grand.balanced_closing()
    print(f"уравновешенность Дт/Кт (начало, оборот, конец): {'да' if balanced else 'НЕТ'}")
    print(f"сумма счетов 1-го уровня = «Итого»: {'да' if totals_equal(level1, grand) else 'НЕТ'}")

    if next_s3 is not None and next_s3.is_file():
        try:
            nxt = read_osv(next_s3)
            breaks = month_carry_breaks(sheet, nxt)
            print(f"разрывов перехода S3 → след. месяц по счетам: {breaks}")
        except XlsFormatError as exc:
            print(f"S3 след. месяца не прочитан: {exc}")

    placed, returned, interest = deposit_flows_from_s1(docs)
    for code in ("51", "57.03", "62", "55.03", "91.01", "91.02"):
        row = sheet.by_code(code)
        if row is None:
            print(f"счёт {code}: нет в ОСВ")
            continue
        print(
            f"счёт {code}: начало {_money(_osv_opening_net(row))} "
            f"Дт {_money(row.turnover_debit)} Кт {_money(row.turnover_credit)} "
            f"конец {_money(_osv_net(row))}"
        )

    if s1_totals is not None:
        row51 = sheet.by_code("51")
        if row51 is not None:
            _compare_money("51 конец vs S1", _osv_net(row51), s1_totals.closing)
    if s13 is not None:
        row51 = sheet.by_code("51")
        if row51 is not None:
            _compare_money("51 конец vs S13", _osv_net(row51), s13.closing)
    if s12_gross is not None:
        row57 = sheet.by_code("57.03")
        if row57 is not None:
            _compare_money("57.03 оборот Дт vs валовая S12", row57.turnover_debit, s12_gross)
    row55 = sheet.by_code("55.03")
    if row55 is not None:
        _compare_money("55.03 оборот Дт vs размещение S1", row55.turnover_debit, placed)
        _compare_money("55.03 оборот Кт vs возврат S1", row55.turnover_credit, returned)
    row91 = sheet.by_code("91.01")
    if row91 is not None:
        _compare_money("91.01 оборот Кт vs проценты S1", row91.turnover_credit, interest)

    row9102 = sheet.by_code("91.02")
    if row9102 is not None:
        acq = acquiring_fee if acquiring_fee is not None else ZERO
        bank_part = money(row9102.turnover_debit - acq)
        print(
            f"91.02: оборот Дт {_money(row9102.turnover_debit)} "
            f"(эквайринг {_money(acq)} + банк {_money(bank_part)})"
        )
        print(
            f"91.02 сальдо: начало {_money(_osv_opening_net(row9102))} "
            f"конец {_money(_osv_net(row9102))} "
            "(для сверки с S2 после получения карточки)"
        )

    if s9_closing is not None and s9a_closing is not None and s9b_closing is not None:
        combined = money(s9a_closing + s9b_closing)
        _compare_money("62.01+62.02 vs S9 счёт 62", combined, s9_closing)
        row62 = sheet.by_code("62")
        if row62 is not None:
            _compare_money("62 конец vs S9", _osv_net(row62), s9_closing)

    return sheet


def print_s9_subaccount(sheet: OsvCounterpartySheet, label: str, s3_row: OsvRow | None) -> None:
    print(
        f"{label}: начало {_money(sheet.opening)} "
        f"Дт {_money(sheet.turnover_in)} Кт {_money(sheet.turnover_out)} "
        f"конец {_money(sheet.closing)}"
    )
    if s3_row is not None:
        _compare_money(f"{label} vs S3", sheet.closing, _osv_net(s3_row))
        _compare_money(
            f"{label} оборот Дт vs S3",
            sheet.turnover_in,
            s3_row.turnover_debit,
        )
        _compare_money(
            f"{label} оборот Кт vs S3",
            sheet.turnover_out,
            s3_row.turnover_credit,
        )


def print_s9_sheet(sheet: OsvCounterpartySheet, label: str) -> None:
    consistent = counterparty_turnover_consistent(sheet)
    debit_side, credit_side = closing_balance_sides(sheet)
    print(f"{label}: строк {len(sheet.rows)}")
    print(
        f"остаток {_money(sheet.opening)} → {_money(sheet.closing)}; "
        f"Дт {_money(sheet.turnover_in)} Кт {_money(sheet.turnover_out)}"
    )
    print(f"сумма оборотов по строкам = счёт: {'да' if consistent else 'НЕТ'}")
    print(f"дебетовые остатки на конец: {_money(debit_side)}")
    print(f"кредитовые остатки (авансы): {_money(credit_side)}")


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


def run(
    folder: Path,
    month_label: str,
    *,
    next_s1: Path | None = None,
    next_s3: Path | None = None,
    prior_s9: Path | None = None,
) -> int:
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
        ("S9", samples.s9),
        ("S9a", samples.s9a),
        ("S9b", samples.s9b),
        ("S12", samples.s12),
        ("S13", samples.s13),
    ):
        print(f"{label}: {path.name if path else 'нет'}")

    if samples.s1 is None:
        print("\nБез S1 проверка невозможна.")
        return 2

    _header("1. S1 · выписка по счёту 51")
    raw_s1 = samples.s1.read_bytes()
    encoding, docs, skipped = load_s1(samples.s1)
    total_in = sum((doc.amount for doc in docs if doc.direction == "in"), ZERO)
    total_out = sum((doc.amount for doc in docs if doc.direction == "out"), ZERO)
    kind_counts = s1_document_kind_counts(raw_s1, encoding)
    print(f"кодировка: {encoding}")
    print(f"документов: {len(docs)} (с ошибками разбора: {skipped})")
    print(f"поступлений: {sum(1 for doc in docs if doc.direction == 'in')} на {_money(total_in)}")
    print(f"списаний: {sum(1 for doc in docs if doc.direction == 'out')} на {_money(total_out)}")
    if kind_counts:
        ordered = ", ".join(f"{name} {count}" for name, count in sorted(kind_counts.items()))
        print(f"типы документов: {ordered}")

    sections = parse_clientbank_daily_sections(raw_s1, encoding=encoding)
    chain_errors = daily_chain_errors(sections)
    daily = totals_from_daily_sections(sections)
    print(f"секций по суткам: {len(sections)}")
    print(f"остаток: {_money(daily.opening)} → {_money(daily.closing)}")
    print(f"ошибок цепочки остатков: {len(chain_errors)}")

    s1_totals = Account51Totals(
        opening=daily.opening,
        total_in=total_in,
        total_out=total_out,
        closing=daily.closing,
    )

    if next_s1 is not None and next_s1.is_file():
        _header("1b. Стыковка конца месяца S1 с началом следующего")
        _enc_next, _docs_next, _skip = load_s1(next_s1)
        next_sections = parse_clientbank_daily_sections(next_s1.read_bytes(), encoding=_enc_next)
        if sections and next_sections:
            last = sorted(sections, key=lambda item: item.period_start)[-1]
            first = sorted(next_sections, key=lambda item: item.period_start)[0]
            gap = _money(last.closing) != _money(first.opening)
            print(
                f"конец {_money(last.closing)} → начало {_money(first.opening)}: "
                f"{'РАСХОЖДЕНИЕ' if gap else 'совпало'}"
            )
        else:
            print("пропущено: нет суточных секций")

    _header("1c. S13 · ОСВ по счёту 51 с дневными оборотами")
    s13: OsvSingleAccountSheet | None = None
    if samples.s13 is None:
        print("пропущено: нет S13")
    else:
        try:
            s13 = read_osv_single_account(samples.s13)
            print_s13_reconcile(s13, sections, s1_totals)
        except XlsFormatError as exc:
            print(f"S13 не прочитан: {exc}")

    acquiring_fee_total: Decimal | None = None
    s12_gross_total: Decimal | None = None
    s9_for_s3: OsvCounterpartySheet | None = None
    s9a_sheet: OsvCounterpartySheet | None = None
    s9b_sheet: OsvCounterpartySheet | None = None

    if samples.s9 is not None:
        try:
            s9_for_s3 = read_osv_counterparties(samples.s9)
        except XlsFormatError:
            s9_for_s3 = None
    if samples.s9a is not None:
        try:
            s9a_sheet = read_osv_counterparties(samples.s9a, account_prefix="62.01")
        except XlsFormatError as exc:
            print(f"S9a не прочитан (prefetch): {exc}")
    if samples.s9b is not None:
        try:
            s9b_sheet = read_osv_counterparties(samples.s9b, account_prefix="62.02")
        except XlsFormatError as exc:
            print(f"S9b не прочитан (prefetch): {exc}")
    if samples.s12 is not None:
        try:
            s12_gross_total = read_osv_5703(samples.s12).root.turnover_debit
        except XlsFormatError:
            s12_gross_total = None

    osv: OsvSheet | None = None

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

    totals_s3: Account51Totals | None = None
    if samples.s3 is not None:
        try:
            if osv is None:
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
        doc_amount_mismatch = 0
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
            if gross - fee != doc.amount:
                doc_amount_mismatch += 1
            acquiring_docs += 1
            gross_by_day[doc.business_date] += gross
            fee_by_day[doc.business_date] += fee

        for index, counterparty in enumerate(s12.root.children, start=1):
            print(f"эквайер {index} валовая {_money(counterparty.turnover_debit)}")

        print(f"эквайринговых поступлений в S1: {acquiring_docs}")
        print(f"документов валовая − комиссия ≠ сумма: {doc_amount_mismatch}")
        if acquiring_skipped:
            print(f"не разобрано назначений: {acquiring_skipped}")
        print(f"валовая по назначениям: {_money(sum(gross_by_day.values(), ZERO))}")
        print(f"комиссия по назначениям: {_money(sum(fee_by_day.values(), ZERO))}")
        print(
            f"валовая − комиссия: "
            f"{_money(sum(gross_by_day.values(), ZERO) - sum(fee_by_day.values(), ZERO))}"
        )
        acquiring_fee_total = sum(fee_by_day.values(), ZERO)

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

    if samples.s3 is not None:
        _header("4b. S3 · полная ОСВ")
        osv = print_s3_full_osv(
            samples.s3,
            s1_totals=s1_totals,
            s13=s13,
            s12_gross=s12_gross_total,
            s9_closing=s9_for_s3.closing if s9_for_s3 else None,
            s9a_closing=s9a_sheet.closing if s9a_sheet else None,
            s9b_closing=s9b_sheet.closing if s9b_sheet else None,
            docs=docs,
            next_s3=next_s3,
            acquiring_fee=acquiring_fee_total,
        )

    _header("5. Комиссии и эквайринг на счёте 91.02")
    if osv is None:
        print("пропущено: нет S3")
    else:
        row9102 = osv.by_code("91.02")
        if row9102 is None:
            print("в ОСВ нет счёта 91.02")
        else:
            fees = ZERO
            if card is not None:
                fees = sum(
                    (
                        row.amount
                        for row in card.rows
                        if row.direction == "out" and row.counter_account == "91.02"
                    ),
                    ZERO,
                )
            acq_fee = acquiring_fee_total if acquiring_fee_total is not None else ZERO
            print(f"оборот Дт 91.02 в ОСВ: {_money(row9102.turnover_debit)}")
            if card is None:
                bank_part = money(row9102.turnover_debit - acq_fee)
                print(f"эквайринг (S12/S1): {_money(acq_fee)}")
                print(f"остаток под комиссии банка (без S2): {_money(bank_part)}")
            else:
                print(f"комиссии банка (списания на 91.02 в S2): {_money(fees)}")
                print(f"комиссия эквайринга (из S12/S1): {_money(acq_fee)}")
                expected = fees + acq_fee
                print(f"ожидается по 91.02: {_money(expected)}")
                print(f"разница: {_money(row9102.turnover_debit - expected)}")

    _header("6. ОСВ 62 по контрагентам (S9)")
    s9_sheet: OsvCounterpartySheet | None = s9_for_s3
    if samples.s9 is None:
        print("пропущено: нет S9")
    elif s9_sheet is not None:
        print_s9_sheet(s9_sheet, "S9")
    else:
        try:
            s9_sheet = read_osv_counterparties(samples.s9)
            print_s9_sheet(s9_sheet, "S9")
        except XlsFormatError as exc:
            print(f"S9 не прочитан: {exc}")

    if prior_s9 is not None and prior_s9.is_file() and s9_sheet is not None:
        try:
            prior_sheet = read_osv_counterparties(prior_s9)
            breaks, union_size = carry_forward_union_breaks(prior_sheet, s9_sheet)
            print(f"разрывов перехода по контрагентам: {breaks}")
            print(f"контрагентов в объединении месяцев: {union_size}")
        except XlsFormatError as exc:
            print(f"пред. S9 не прочитан: {exc}")

    _header("6b. ОСВ 62.01 и 62.02 (S9a / S9b)")
    if samples.s9a is None and samples.s9b is None:
        print("пропущено: нет S9a/S9b")
    else:
        row6201 = osv.by_code("62.01") if osv is not None else None
        row6202 = osv.by_code("62.02") if osv is not None else None
        if s9a_sheet is not None:
            print_s9_subaccount(s9a_sheet, "S9a 62.01", row6201)
        else:
            print("S9a: нет файла")
        if s9b_sheet is not None:
            print_s9_subaccount(s9b_sheet, "S9b 62.02", row6202)
        else:
            print("S9b: нет файла")
        if s9a_sheet is not None and s9b_sheet is not None:
            combined = money(s9a_sheet.closing + s9b_sheet.closing)
            print(f"62.01 + 62.02 (чистые): {_money(combined)}")

    _header("7. Набор правил v1")
    rules = pack_rule_views()
    if card is None or not pairs:
        print("режим: только охват (нет S2 или нет пар S1 ↔ S2)")
        report_pack_coverage(docs, rules)
    else:
        print("режим: точность против эталона S2")
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

    _header("8. Депозитные операции (investing)")
    report_deposit_investing(docs, rules)

    _header("9. Ожидаемые образцы")
    print("S11 (журнал реализаций): ожидается образец")
    print("S10 (карточка 62): ожидается образец")
    print("S2 (карточка 51): для hold-out месяца без карточки точность набора не оценивается")
    return 0


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверка месяца FA-R03: S1/S2/S3/S9/S12/S13 и набор правил.",
    )
    parser.add_argument("folder", type=Path, help="папка с образцами (S1_, S2_, …)")
    parser.add_argument("--month", required=True, help="месяц в формате ГГГГ-ММ")
    parser.add_argument(
        "--next-s1",
        type=Path,
        default=None,
        help="S1 следующего месяца для стыковки остатков",
    )
    parser.add_argument(
        "--prior-s9",
        type=Path,
        default=None,
        help="S9 предыдущего месяца для перехода остатков по контрагентам",
    )
    parser.add_argument(
        "--next-s3",
        type=Path,
        default=None,
        help="S3 следующего месяца для перехода остатков по счетам",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    return run(
        args.folder,
        args.month,
        next_s1=args.next_s1,
        next_s3=args.next_s3,
        prior_s9=args.prior_s9,
    )


if __name__ == "__main__":
    sys.exit(main())
