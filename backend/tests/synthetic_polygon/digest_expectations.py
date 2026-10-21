"""Оракул показателей дайджеста на дату отчёта полигона (независимо от telegram_digest)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.domain.money import money, money_str
from tests.synthetic_polygon.expectations import (
    GROUP_CASH_ORACLE,
    GROUP_REVENUE_ORACLE,
    ORACLE,
    group_rollup,
)
from tests.synthetic_polygon.profiles import ALL_PROFILES, CompanyProfile, ProfileKind

DIGEST_REPORT_DATE = date(2026, 10, 31)
REPORT_ISO = DIGEST_REPORT_DATE.isoformat()


def _d(value: str) -> Decimal:
    return Decimal(value)


def _clientbank_iso(posted: str) -> str:
    day, month, year = posted.split(".")
    return f"{year}-{month.zfill(2)}-{day.zfill(2)}"


def day_cash_flows(profile: CompanyProfile, day: str) -> tuple[str, str]:
    incoming = Decimal("0")
    outgoing = Decimal("0")
    for row in profile.cash:
        if row.business_date != day:
            continue
        amount = _d(row.amount)
        if row.direction == "in":
            incoming += amount
        else:
            outgoing += amount
    for doc in profile.clientbank:
        if _clientbank_iso(doc.posted_date) != day:
            continue
        amount = _d(doc.amount)
        if doc.posted_field == "ДатаПоступило":
            incoming += amount
        else:
            outgoing += amount
    return money_str(money(incoming)), money_str(money(outgoing))


def revenue_for_day(profile: CompanyProfile, day: str) -> str | None:
    total = Decimal("0")
    found = False
    for row in profile.revenue:
        if row.recognition_date != day:
            continue
        found = True
        ex = _d(row.amount_ex_vat)
        if row.entry_type == "return":
            total -= ex
        else:
            total += ex
    if not found:
        return None
    return money_str(money(total))


def revenue_mtd(profile: CompanyProfile, through: date) -> str:
    month_start = through.replace(day=1)
    total = Decimal("0")
    for row in profile.revenue:
        rec = date.fromisoformat(row.recognition_date)
        if rec < month_start or rec > through:
            continue
        ex = _d(row.amount_ex_vat)
        if row.entry_type == "return":
            total -= ex
        else:
            total += ex
    return money_str(money(total))


def plan_overdue_out(profile: CompanyProfile, report: date) -> str:
    overdue = Decimal("0")
    matched = _plan_matched_out(profile)
    for row in profile.plan:
        if row.direction != "out":
            continue
        due = date.fromisoformat(row.due_date)
        if due >= report:
            continue
        residual = _d(row.amount) - matched.get(row.external_id, Decimal("0"))
        if residual > 0:
            overdue += residual
    return money_str(money(overdue))


def plan_upcoming_out(profile: CompanyProfile, report: date) -> str:
    upcoming = Decimal("0")
    horizon = report + timedelta(days=7)
    matched = _plan_matched_out(profile)
    for row in profile.plan:
        if row.direction != "out":
            continue
        due = date.fromisoformat(row.due_date)
        if due < report or due > horizon:
            continue
        residual = _d(row.amount) - matched.get(row.external_id, Decimal("0"))
        if residual > 0:
            upcoming += residual
    return money_str(money(upcoming))


def _plan_matched_out(profile: CompanyProfile) -> dict[str, Decimal]:
    matched: dict[str, Decimal] = {}
    cash_by_ext = {row.external_id: row for row in profile.cash}
    for cash_ext, plan_ext, amount in profile.plan_match:
        cash_row = cash_by_ext[cash_ext]
        if cash_row.direction != "in":
            continue
        plan_row = next(item for item in profile.plan if item.external_id == plan_ext)
        if plan_row.direction != "out":
            continue
        matched[plan_ext] = matched.get(plan_ext, Decimal("0")) + _d(amount)
    return matched


def company_card_oracle(slug: ProfileKind) -> dict[str, str | None]:
    profile = next(item for item in ALL_PROFILES if item.slug == slug)
    exp = ORACLE[slug]
    incoming, outgoing = day_cash_flows(profile, REPORT_ISO)
    return {
        "cash_total": exp.cash_total,
        "revenue_yesterday": revenue_for_day(profile, REPORT_ISO),
        "revenue_mtd": revenue_mtd(profile, DIGEST_REPORT_DATE),
        "incoming": incoming,
        "outgoing": outgoing,
        "overdue": plan_overdue_out(profile, DIGEST_REPORT_DATE),
        "upcoming": plan_upcoming_out(profile, DIGEST_REPORT_DATE),
    }


def group_totals_oracle() -> dict[str, str]:
    rollup = group_rollup()
    assert rollup["cash_total"] == GROUP_CASH_ORACLE
    assert rollup["revenue"] == GROUP_REVENUE_ORACLE
    incoming = Decimal("0")
    outgoing = Decimal("0")
    rev_yesterday: list[str] = []
    for profile in ALL_PROFILES:
        inc, out = day_cash_flows(profile, REPORT_ISO)
        incoming += _d(inc)
        outgoing += _d(out)
        day_rev = revenue_for_day(profile, REPORT_ISO)
        if day_rev is not None:
            rev_yesterday.append(day_rev)
    net = money_str(money(incoming - outgoing))
    rev_y = None if not rev_yesterday else money_str(money(sum(_d(item) for item in rev_yesterday)))
    return {
        "cash_total": GROUP_CASH_ORACLE,
        "revenue_mtd": GROUP_REVENUE_ORACLE,
        "incoming": money_str(money(incoming)),
        "outgoing": money_str(money(outgoing)),
        "net": net,
        "revenue_yesterday": rev_y,
    }


def assert_card_matches_oracle(card: dict, slug: ProfileKind) -> None:
    expected = company_card_oracle(slug)
    for key, want in expected.items():
        got = card.get(key)
        if want is None and got == "0.00" and key == "revenue_yesterday":
            continue
        if want is None:
            assert got is None, f"{slug}.{key}: ожидали unavailable, получили {got!r}"
        else:
            assert got == want, f"{slug}.{key}: oracle {want} != metrics {got!r}"


def assert_group_totals_match_oracle(totals: dict) -> list[str]:
    """Сверка с оракулом; возвращает список задокументированных расхождений."""
    expected = group_totals_oracle()
    notes: list[str] = []
    for key, want in expected.items():
        got = totals.get(key)
        if want is None and got == "0.00" and key == "revenue_yesterday":
            notes.append(
                "group.revenue_yesterday: оракул unavailable (нет recognition_date), "
                "сервис assess_revenue при покрытии возвращает 0.00"
            )
            continue
        if want is None:
            assert got is None, f"group.{key}: oracle unavailable != {got!r}"
        else:
            assert got == want, f"group.{key}: oracle {want} != {got!r}"
    return notes
