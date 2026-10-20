"""Декларативные профили трёх вымышленных компаний (единый источник строк импорта)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ProfileKind = Literal["services", "retail", "subscription"]


@dataclass(frozen=True)
class TaxParams:
    """Явные налоговые параметры сценария; не выводятся из названия режима."""

    legal_form: str
    vat_payer: bool
    default_vat_rate: str
    usn_object: str | None = None
    cash_method_for_usn: bool | None = None
    note: str = ""


@dataclass(frozen=True)
class BalanceRow:
    wallet_code: str
    as_of: str
    balance: str
    currency: str = "RUB"


@dataclass(frozen=True)
class CashRow:
    external_id: str
    wallet_code: str
    business_date: str
    direction: Literal["in", "out"]
    amount: str
    counterparty_inn: str = ""
    counterparty_name: str = ""
    description: str = ""
    document_number: str = ""
    category_code: str = "operating"


@dataclass(frozen=True)
class RevenueRow:
    external_id: str
    recognition_date: str
    document_number: str
    counterparty_inn: str
    amount_ex_vat: str
    vat_amount: str
    amount_inc_vat: str
    entry_type: Literal["sale", "return"] = "sale"


@dataclass(frozen=True)
class PlanRow:
    external_id: str
    direction: Literal["in", "out"]
    amount: str
    due_date: str
    expected_date: str
    wallet_code: str = "main"
    confidence: str = "expected"
    priority: str = "normal"
    category_code: str = "operating"


@dataclass(frozen=True)
class BudgetRow:
    year: int
    month: int
    basis: Literal["cash", "revenue"]
    metric_type: Literal["cash_in", "cash_out", "revenue"]
    amount: str
    category_code: str = "operating"
    direction_code: str = ""
    distribution_method: str = "calendar_days"


@dataclass(frozen=True)
class ClientBankDoc:
    number: str
    date: str
    amount: str
    payer_inn: str
    payer_name: str
    payee_inn: str
    payee_name: str
    purpose: str
    posted_field: Literal["ДатаПоступило", "ДатаСписано"]
    posted_date: str


@dataclass(frozen=True)
class CompanyProfile:
    slug: ProfileKind
    display_name: str
    industry_label: str
    tax: TaxParams
    balances: tuple[BalanceRow, ...] = ()
    cash: tuple[CashRow, ...] = ()
    clientbank: tuple[ClientBankDoc, ...] = ()
    revenue: tuple[RevenueRow, ...] = ()
    plan: tuple[PlanRow, ...] = ()
    budget: tuple[BudgetRow, ...] = ()
    plan_match: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)
    """(cash_external_id, plan_external_id, match_amount) после commit."""


SERVICES = CompanyProfile(
    slug="services",
    display_name="Synth Services LLC",
    industry_label="услуги",
    tax=TaxParams(
        legal_form="OOO",
        vat_payer=True,
        default_vat_rate="0.20",
        usn_object=None,
        note="НДС 20% задан явно в строках revenue; УСН не моделируется.",
    ),
    balances=(BalanceRow("main", "2026-10-01", "50000.00"),),
    cash=(
        CashRow("svc-c1", "main", "2026-10-05", "in", "12000.00", "7700000101", "Synth Client One", "Оплата услуг", "SVC-01"),
        CashRow("svc-c2", "main", "2026-10-15", "in", "8000.00", "7700000102", "Synth Client Two", "Аванс за проект", "SVC-02"),
        CashRow("svc-c3", "main", "2026-10-20", "out", "3000.00", "7700000199", "Synth Vendor", "Подряд", "SVC-OUT-1"),
    ),
    revenue=(
        RevenueRow("svc-r1", "2026-10-10", "SVC-R-10", "7700000101", "10000.00", "2000.00", "12000.00"),
        RevenueRow("svc-r2", "2026-10-18", "SVC-R-18", "7700000102", "5000.00", "1000.00", "6000.00"),
    ),
    plan=(PlanRow("svc-p1", "out", "4000.00", "2026-10-28", "2026-10-28"),),
    budget=(BudgetRow(2026, 10, "cash", "cash_out", "12000.00"),),
)

RETAIL = CompanyProfile(
    slug="retail",
    display_name="Synth Retail LLC",
    industry_label="торговля без складского учёта",
    tax=TaxParams(
        legal_form="OOO",
        vat_payer=True,
        default_vat_rate="0.20",
        usn_object=None,
        note="Одна продажа с НДС 0 через явные нулевые vat_amount.",
    ),
    balances=(BalanceRow("main", "2026-10-01", "25000.00"),),
    cash=(
        CashRow("ret-c1", "main", "2026-10-04", "in", "15000.00", "7700000201", "Synth Buyer", "Розничная оплата", "RET-01"),
        CashRow("ret-c2", "main", "2026-10-08", "out", "2500.00", "7700000299", "Synth Supplier", "Закупка", "RET-OUT-1"),
    ),
    clientbank=(
        ClientBankDoc(
            "ret-cb1",
            "12.10.2026",
            "7200.00",
            "7700000202",
            "Synth Buyer CB",
            "7700000300",
            "Synth Retail LLC",
            "Оплата по счёту",
            "ДатаПоступило",
            "12.10.2026",
        ),
    ),
    revenue=(
        RevenueRow("ret-r1", "2026-10-05", "RET-05", "7700000201", "24000.00", "4800.00", "28800.00"),
        RevenueRow("ret-r2", "2026-10-11", "RET-11", "7700000202", "6000.00", "1200.00", "7200.00"),
        RevenueRow("ret-r3", "2026-10-20", "RET-RET-20", "7700000201", "3000.00", "600.00", "3600.00", "return"),
        RevenueRow(
            "ret-r4",
            "2026-10-22",
            "RET-22",
            "7700000203",
            "1000.00",
            "0.00",
            "1000.00",
        ),
    ),
    budget=(BudgetRow(2026, 10, "revenue", "revenue", "30000.00"),),
)

SUBSCRIPTION = CompanyProfile(
    slug="subscription",
    display_name="Synth Subscript LLC",
    industry_label="подписочный бизнес",
    tax=TaxParams(
        legal_form="OOO",
        vat_payer=True,
        default_vat_rate="0.20",
        usn_object="income",
        cash_method_for_usn=True,
        note="УСН «доходы» и кассовый метод — только метаданные сценария, не расчёт налога.",
    ),
    balances=(BalanceRow("main", "2026-10-01", "1000.00"),),
    cash=(
        CashRow("sub-c1", "main", "2026-10-03", "in", "1200.00", "7700000401", "Synth Sub A", "Подписка окт", "SUB-01"),
        CashRow("sub-c2", "main", "2026-10-10", "in", "1200.00", "7700000402", "Synth Sub B", "Подписка окт", "SUB-02"),
        CashRow("sub-c3", "main", "2026-10-17", "in", "1200.00", "7700000403", "Synth Sub C", "Подписка окт", "SUB-03"),
        CashRow("sub-c4", "main", "2026-10-24", "in", "1200.00", "7700000404", "Synth Sub D", "Подписка окт", "SUB-04"),
    ),
    revenue=(
        RevenueRow("sub-r1", "2026-10-01", "SUB-R-1", "7700000401", "1000.00", "200.00", "1200.00"),
        RevenueRow("sub-r2", "2026-10-15", "SUB-R-2", "7700000402", "1000.00", "200.00", "1200.00"),
        RevenueRow("sub-r3", "2026-10-28", "SUB-R-3", "7700000403", "1000.00", "200.00", "1200.00"),
    ),
    plan=(PlanRow("sub-p1", "in", "2400.00", "2026-10-30", "2026-10-31"),),
    plan_match=(("sub-c1", "sub-p1", "1200.00"),),
)

ALL_PROFILES: tuple[CompanyProfile, ...] = (SERVICES, RETAIL, SUBSCRIPTION)
