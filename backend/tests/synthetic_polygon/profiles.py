"""Декларативные профили трёх вымышленных компаний (единый источник строк импорта)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ProfileKind = Literal[
    "services",
    "retail",
    "subscription",
    "gap_digest",
    "cashflow_sections",
    "receivable_demo",
]


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

# Отдельный профиль для FA-R09.P2 (сигналы дайджеста); не входит в ALL_PROFILES / group ORACLE.
GAP_DIGEST = CompanyProfile(
    slug="gap_digest",
    display_name="Synth Gap Digest LLC",
    industry_label="сценарий дефицита",
    tax=TaxParams(
        legal_form="OOO",
        vat_payer=False,
        default_vat_rate="0.00",
        note="Только дайджест/сигналы; не влияет на групповой ORACLE 117500/46000.",
    ),
    balances=(BalanceRow("main", "2026-10-01", "5000.00"),),
    cash=(
        CashRow(
            "gap-c1",
            "main",
            "2026-10-12",
            "out",
            "350000.00",
            "",
            "Privacy Oracle CP",
            "Крупный платёж",
            "GAP-OUT-1",
        ),
    ),
    plan=(PlanRow("gap-p1", "out", "90000.00", "2026-11-05", "2026-11-05"),),
)

# FA-R06.1-P1: все секции ОДДС + unmapped/technical; не в ALL_PROFILES / group ORACLE.
CASHFLOW_SECTIONS = CompanyProfile(
    slug="cashflow_sections",
    display_name="Synth Cashflow Sections LLC",
    industry_label="сценарий секций ОДДС",
    tax=TaxParams(
        legal_form="OOO",
        vat_payer=False,
        default_vat_rate="0.00",
        note="Только cashflow P1; internal transfer связывается через POST /transfers/link.",
    ),
    balances=(
        BalanceRow("main", "2026-10-01", "100000.00"),
        BalanceRow("reserve", "2026-10-01", "0.00"),
    ),
    cash=(
        CashRow("cfs-op-in", "main", "2026-10-04", "in", "5000.00", category_code="operating"),
        CashRow("cfs-op-out", "main", "2026-10-06", "out", "1200.00", category_code="operating"),
        CashRow(
            "cfs-fin-in",
            "main",
            "2026-10-08",
            "in",
            "10000.00",
            category_code="owner_contribution",
        ),
        CashRow("cfs-inv-out", "main", "2026-10-10", "out", "800.00", category_code="investing"),
        CashRow(
            "cfs-unmapped",
            "main",
            "2026-10-12",
            "in",
            "300.00",
            "",
            "No Category Payer",
            "Без категории",
            "CFS-U1",
            "",
        ),
        CashRow("cfs-tech-out", "main", "2026-10-14", "out", "150.00", category_code="technical"),
        CashRow(
            "cfs-xfer-out",
            "main",
            "2026-10-16",
            "out",
            "2000.00",
            category_code="operating",
            description="На резерв",
        ),
        CashRow(
            "cfs-xfer-in",
            "reserve",
            "2026-10-16",
            "in",
            "2000.00",
            category_code="operating",
            description="С основного",
        ),
    ),
)

# FA-R06.1-P2: насыщенная дебиторка; не в ALL_PROFILES / group ORACLE.
RECEIVABLE_DEMO = CompanyProfile(
    slug="receivable_demo",
    display_name="Synth Receivable Demo LLC",
    industry_label="сценарий дебиторки P2",
    tax=TaxParams(
        legal_form="OOO",
        vat_payer=True,
        default_vat_rate="0.20",
        note="FA-R06.1-P2; gross AR, явные matches через harness.",
    ),
    balances=(BalanceRow("main", "2026-10-01", "20000.00"),),
    cash=(
        CashRow(
            "rd-c-adv",
            "main",
            "2026-10-08",
            "in",
            "15000.00",
            "7700000902",
            "Synth AR Two",
            "Аванс без match",
            "RD-ADV",
        ),
        CashRow(
            "rd-c-b",
            "main",
            "2026-10-11",
            "in",
            "4000.00",
            "7700000901",
            "Synth AR One",
            "Частичная оплата B",
            "RD-B-PAY",
        ),
        CashRow(
            "rd-c-paid",
            "main",
            "2026-10-29",
            "in",
            "10000.00",
            "7700000901",
            "Synth AR One",
            "Полная оплата",
            "RD-PAID-PAY",
        ),
        CashRow(
            "rd-c-over",
            "main",
            "2026-10-30",
            "in",
            "600.00",
            "7700000901",
            "Synth AR One",
            "Переполнение match",
            "RD-OVER-PAY1",
        ),
        CashRow(
            "rd-c-over2",
            "main",
            "2026-10-30",
            "in",
            "500.00",
            "7700000901",
            "Synth AR One",
            "Переполнение match 2",
            "RD-OVER-PAY2",
        ),
    ),
    revenue=(
        RevenueRow("rd-r-a", "2026-10-05", "RD-A", "7700000901", "10000.00", "2000.00", "12000.00"),
        RevenueRow("rd-r-b", "2026-10-10", "RD-B", "7700000901", "8333.33", "1666.67", "10000.00"),
        RevenueRow("rd-r-c-sale", "2026-10-12", "RD-C", "7700000901", "6666.67", "1333.33", "8000.00"),
        RevenueRow(
            "rd-r-c-ret",
            "2026-10-14",
            "RD-C-RET",
            "7700000901",
            "1666.67",
            "333.33",
            "2000.00",
            "return",
        ),
        RevenueRow("rd-r-d", "2026-10-20", "RD-D", "7700000902", "5000.00", "1000.00", "6000.00"),
        RevenueRow("rd-r-e", "2026-10-25", "RD-E", "", "1250.00", "250.00", "1500.00"),
        RevenueRow("rd-r-f1", "2026-09-20", "RD-F1", "7700000902", "4166.67", "833.33", "5000.00"),
        RevenueRow("rd-r-f2", "2026-08-25", "RD-F2", "7700000902", "4166.67", "833.33", "5000.00"),
        RevenueRow("rd-r-f3", "2026-05-15", "RD-F3", "7700000902", "4166.67", "833.33", "5000.00"),
        RevenueRow("rd-r-b30", "2026-10-01", "RD-B30", "7700000902", "0.83", "0.17", "1.00"),
        RevenueRow("rd-r-b31", "2026-09-30", "RD-B31", "7700000902", "0.83", "0.17", "1.00"),
        RevenueRow("rd-r-b60", "2026-09-01", "RD-B60", "7700000902", "0.83", "0.17", "1.00"),
        RevenueRow("rd-r-b61", "2026-08-31", "RD-B61", "7700000902", "0.83", "0.17", "1.00"),
        RevenueRow("rd-r-b90", "2026-08-02", "RD-B90", "7700000902", "0.83", "0.17", "1.00"),
        RevenueRow("rd-r-b91", "2026-08-01", "RD-B91", "7700000902", "0.83", "0.17", "1.00"),
        RevenueRow("rd-r-paid", "2026-10-28", "RD-PAID", "7700000901", "8333.33", "1666.67", "10000.00"),
        RevenueRow("rd-r-over", "2026-10-30", "RD-OVER", "7700000901", "833.33", "166.67", "1000.00"),
    ),
)

ALL_PROFILES: tuple[CompanyProfile, ...] = (SERVICES, RETAIL, SUBSCRIPTION)
