"""Независимый пересчёт ожиданий из декларативных профилей (Decimal)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.money import money, money_str
from tests.synthetic_polygon.profiles import ALL_PROFILES, CompanyProfile, ProfileKind


@dataclass(frozen=True)
class DashboardExpectation:
    opening_balance: str
    cash_in: str
    cash_out: str
    net_cash_flow: str
    cash_total: str
    operation_count: int
    revenue_net_ex_vat: str
    revenue_count: int


def _d(value: str) -> Decimal:
    return Decimal(value)


def _sum_cash(profile: CompanyProfile) -> tuple[Decimal, Decimal]:
    cash_in = Decimal("0")
    cash_out = Decimal("0")
    for row in profile.cash:
        amount = _d(row.amount)
        if row.direction == "in":
            cash_in += amount
        else:
            cash_out += amount
    for doc in profile.clientbank:
        amount = _d(doc.amount)
        if doc.posted_field == "ДатаПоступило":
            cash_in += amount
        else:
            cash_out += amount
    return cash_in, cash_out


def _sum_revenue_net(profile: CompanyProfile) -> Decimal:
    total = Decimal("0")
    for row in profile.revenue:
        ex = _d(row.amount_ex_vat)
        if row.entry_type == "return":
            total -= ex
        else:
            total += ex
    return money(total)


def expectation_for(profile: CompanyProfile) -> DashboardExpectation:
    opening = _d(profile.balances[0].balance) if profile.balances else Decimal("0")
    cash_in, cash_out = _sum_cash(profile)
    net = money(cash_in - cash_out)
    cash_total = money(opening + net)
    op_count = len(profile.cash) + len(profile.clientbank)
    revenue = _sum_revenue_net(profile)
    return DashboardExpectation(
        opening_balance=money_str(opening),
        cash_in=money_str(money(cash_in)),
        cash_out=money_str(money(cash_out)),
        net_cash_flow=money_str(net),
        cash_total=money_str(cash_total),
        operation_count=op_count,
        revenue_net_ex_vat=money_str(revenue),
        revenue_count=len(profile.revenue),
    )


# Оракул: значения сверены вручную с профилями (второй независимый путь для unit-теста).
ORACLE: dict[ProfileKind, DashboardExpectation] = {
    "services": DashboardExpectation(
        opening_balance="50000.00",
        cash_in="20000.00",
        cash_out="3000.00",
        net_cash_flow="17000.00",
        cash_total="67000.00",
        operation_count=3,
        revenue_net_ex_vat="15000.00",
        revenue_count=2,
    ),
    "retail": DashboardExpectation(
        opening_balance="25000.00",
        cash_in="22200.00",
        cash_out="2500.00",
        net_cash_flow="19700.00",
        cash_total="44700.00",
        operation_count=3,
        revenue_net_ex_vat="28000.00",
        revenue_count=4,
    ),
    "subscription": DashboardExpectation(
        opening_balance="1000.00",
        cash_in="4800.00",
        cash_out="0.00",
        net_cash_flow="4800.00",
        cash_total="5800.00",
        operation_count=4,
        revenue_net_ex_vat="3000.00",
        revenue_count=3,
    ),
}


def group_rollup() -> dict[str, str]:
    total_cash = Decimal("0")
    total_revenue = Decimal("0")
    for profile in ALL_PROFILES:
        exp = expectation_for(profile)
        total_cash += _d(exp.cash_total)
        total_revenue += _d(exp.revenue_net_ex_vat)
    return {
        "cash_total": money_str(money(total_cash)),
        "revenue": money_str(money(total_revenue)),
    }


# Групповая выручка: 15000 + 28000 + 3000 = 46000 (ручная проверка).
GROUP_REVENUE_ORACLE = "46000.00"
GROUP_CASH_ORACLE = "117500.00"


@dataclass(frozen=True)
class PlanMoveForecastOracle:
    """План → перенос expected_date; деньги (cash_total) не меняются."""

    plan_external_id: str
    amount: str
    due_date: str
    expected_before: str
    moved_expected: str
    as_of: str
    cash_total_unchanged: str
    forecast_contribution_date_before: str
    forecast_contribution_date_after: str


# svc-p1: out 4000, due/expected 2026-10-28; as_of 2026-11-01 — просрочка, поток на as_of.
# После переноса expected на 2026-11-05 — поток на новую expected_date (не меняя posted cash).
SERVICES_PLAN_MOVE = PlanMoveForecastOracle(
    plan_external_id="svc-p1",
    amount="4000.00",
    due_date="2026-10-28",
    expected_before="2026-10-28",
    moved_expected="2026-11-05",
    as_of="2026-11-01",
    cash_total_unchanged="67000.00",
    forecast_contribution_date_before="2026-11-01",
    # После переноса expected просроченный payable остаётся на as_of (см. test_f5 plan_api).
    forecast_contribution_date_after="2026-11-01",
)


def assert_oracle_matches_profiles() -> None:
    for profile in ALL_PROFILES:
        computed = expectation_for(profile)
        oracle = ORACLE[profile.slug]
        if computed != oracle:
            raise AssertionError(f"{profile.slug}: computed {computed} != oracle {oracle}")
