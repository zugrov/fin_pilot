import uuid
from datetime import date, datetime
from decimal import Decimal

from app.domain.billing.periods import MOSCOW
from app.domain.money import money, money_str
from app.domain.revenue import (
    GROUP_REVENUE_LABEL,
    SaleFact,
    assess_revenue,
    input_revision,
)
from app.models.cash import CashCategory, CashTransaction, OpeningBalance, TransferGroup, Wallet
from app.models.imports import SourceConnection
from app.models.revenue import RevenueEntry
from app.services.cash_service import company_summary, summary_payload
from sqlalchemy import select
from sqlalchemy.orm import Session

SECTIONS = ("operating", "investing", "financing", "technical", "unmapped")


def default_period(at: datetime) -> tuple[date, date]:
    local = at.astimezone(MOSCOW).date()
    return local.replace(day=1), local


def revenue_snapshot(session: Session, company_id: uuid.UUID, tenant_id: uuid.UUID, period):
    date_from, date_to = period
    entries = list(
        session.scalars(
            select(RevenueEntry).where(
                RevenueEntry.tenant_id == tenant_id,
                RevenueEntry.company_id == company_id,
                RevenueEntry.status == "posted",
                RevenueEntry.recognition_date >= date_from,
                RevenueEntry.recognition_date <= date_to,
            )
        ).all()
    )
    sources = list(
        session.scalars(
            select(SourceConnection).where(
                SourceConnection.tenant_id == tenant_id,
                SourceConnection.company_id == company_id,
                SourceConnection.dataset == "revenue",
                SourceConnection.status == "active",
            )
        ).all()
    )
    covered, coverage = _coverage(sources, date_to)
    facts = tuple(
        SaleFact(
            str(item.id),
            item.entry_type,
            item.vat_basis,
            item.amount_ex_vat,
            item.amount_inc_vat,
        )
        for item in entries
    )
    view = assess_revenue(facts, covered=covered)
    flags = list(view.quality_flags)
    if sources and not covered and "partial_period" not in flags and not entries:
        flags = ["partial_period"]
        view_amount = None
        label = view.label
        basis = "unavailable"
        ids: tuple[str, ...] = ()
    else:
        view_amount = view.amount
        label = view.label
        basis = view.metric_basis
        ids = view.entry_ids
    return {
        "amount": None if view_amount is None else money_str(view_amount),
        "label": label,
        "metric_basis": basis,
        "quality_flags": flags,
        "entry_ids": list(ids),
        "coverage_through": None if coverage is None else coverage.isoformat(),
        "count": len(entries),
        "net_sum": _net_sum(entries),
    }


def dashboard_payload(session: Session, company, at: datetime, period: tuple[date, date]) -> dict:
    cash = summary_payload(company_summary(session, company, at))
    revenue = revenue_snapshot(session, company.id, company.tenant_id, period)
    flags = [item for item in cash["quality_flags"] if item != "missing_revenue_source"]
    for item in revenue["quality_flags"]:
        if item not in flags:
            flags.append(item)
    flow = cashflow_payload(session, company, at, period)
    for item in flow["quality_flags"]:
        if item not in flags:
            flags.append(item)
    cash_in, cash_out, net_flow, operation_count = _period_movement(flow, cash["cash_total"])
    revision = input_revision(
        {
            "cash_total": cash["cash_total"] or "",
            "cash_in": cash_in or "",
            "cash_out": cash_out or "",
            "revenue": revenue["amount"] or "",
            "revenue_count": str(revenue["count"]),
            "coverage": revenue["coverage_through"] or "",
            "flow": net_flow or "",
        }
    )
    return {
        "company_id": str(company.id),
        "as_of": at.isoformat(),
        "date_from": period[0].isoformat(),
        "date_to": period[1].isoformat(),
        "coverage_through": revenue["coverage_through"],
        "input_revision": revision,
        "metric_basis": revenue["metric_basis"],
        "cash_basis": cash["metric_basis"],
        "quality_flags": flags,
        "revenue_label": revenue["label"],
        "drilldown_refs": {"revenue_entry_ids": revenue["entry_ids"]},
        "values": {
            "cash_total": cash["cash_total"],
            "opening_balance": _opening_total(session, company),
            "cash_in": cash_in,
            "cash_out": cash_out,
            "available": cash["available"],
            "restricted": cash["restricted"],
            "revenue": revenue["amount"],
            "net_cash_flow": net_flow,
            "operation_count": operation_count,
        },
    }


def cashflow_payload(session: Session, company, at: datetime, period: tuple[date, date]) -> dict:
    date_from, date_to = period
    rows = list(
        session.scalars(
            select(CashTransaction).where(
                CashTransaction.tenant_id == company.tenant_id,
                CashTransaction.company_id == company.id,
                CashTransaction.status == "posted",
                CashTransaction.business_date >= date_from,
                CashTransaction.business_date <= date_to,
            )
        ).all()
    )
    incoming = {code: Decimal("0") for code in SECTIONS}
    outgoing = {code: Decimal("0") for code in SECTIONS}
    ids: dict[str, list[str]] = {code: [] for code in SECTIONS}
    external_count = 0
    flags: list[str] = []
    wallets = session.scalars(
        select(Wallet).where(
            Wallet.tenant_id == company.tenant_id,
            Wallet.company_id == company.id,
            Wallet.is_active.is_(True),
        )
    ).all()
    if any(_missing_anchor(session, wallet) for wallet in wallets):
        flags.append("missing_opening_balance")
    for row in rows:
        if _internal(session, row):
            continue
        section = _section(session, row)
        if section == "unmapped" and "unclassified_operations" not in flags:
            flags.append("unclassified_operations")
        external_count += 1
        if row.direction == "in":
            incoming[section] += row.amount
        else:
            outgoing[section] += row.amount
        ids[section].append(str(row.id))
    external_in = sum(incoming.values(), Decimal("0"))
    external_out = sum(outgoing.values(), Decimal("0"))
    sections = [
        {
            "code": code,
            "in": money_str(incoming[code]),
            "out": money_str(outgoing[code]),
            "transaction_ids": ids[code][:100],
        }
        for code in SECTIONS
    ]
    return {
        "company_id": str(company.id),
        "as_of": at.isoformat(),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "input_revision": input_revision(
            {
                "in": money_str(external_in),
                "out": money_str(external_out),
                "rows": str(len(rows)),
            }
        ),
        "quality_flags": flags,
        "metric_basis": "cash",
        "external_count": external_count,
        "net_external": money_str(money(external_in - external_out)),
        "sections": sections,
        "drilldown_refs": {
            "transaction_ids": [item for code in SECTIONS for item in ids[code][:100]]
        },
    }


def group_revenue(amounts: list[str | None]) -> tuple[str | None, str]:
    if not amounts or any(item is None for item in amounts):
        return None, GROUP_REVENUE_LABEL
    total = sum((Decimal(item) for item in amounts if item is not None), Decimal("0"))
    return money_str(total), GROUP_REVENUE_LABEL


def _coverage(sources: list[SourceConnection], date_to: date) -> tuple[bool, date | None]:
    if not sources:
        return False, None
    dates = [item.coverage_through for item in sources]
    if any(item is None for item in dates):
        return False, None
    known = [item for item in dates if item is not None]
    coverage = min(known)
    return coverage >= date_to, coverage


def _net_sum(entries: list[RevenueEntry]) -> str:
    total = Decimal("0")
    for item in entries:
        if item.amount_ex_vat is None:
            continue
        if item.entry_type == "return":
            total -= item.amount_ex_vat
        else:
            total += item.amount_ex_vat
    return money_str(total)


def _period_movement(
    flow: dict, cash_total: str | None
) -> tuple[str | None, str | None, str | None, int | None]:
    # Остаток без начальной точки неизвестен. Обороты уже загруженных операций
    # при этом известны. Ноль без единой операции здесь подменил бы отсутствие данных.
    count = flow["external_count"]
    incomplete = cash_total is None or "missing_opening_balance" in flow["quality_flags"]
    if incomplete and count == 0:
        return None, None, None, None
    incoming = sum((Decimal(item["in"]) for item in flow["sections"]), Decimal("0"))
    outgoing = sum((Decimal(item["out"]) for item in flow["sections"]), Decimal("0"))
    return money_str(incoming), money_str(outgoing), flow["net_external"], count


def _opening_total(session: Session, company) -> str | None:
    wallets = list(
        session.scalars(
            select(Wallet).where(
                Wallet.tenant_id == company.tenant_id,
                Wallet.company_id == company.id,
                Wallet.is_active.is_(True),
            )
        ).all()
    )
    if not wallets:
        return None
    total = Decimal("0")
    for wallet in wallets:
        opening = session.scalar(
            select(OpeningBalance).where(
                OpeningBalance.wallet_id == wallet.id,
                OpeningBalance.status == "active",
            )
        )
        if opening is None:
            return None
        total += opening.amount
    return money_str(total)


def _section(session: Session, row: CashTransaction) -> str:
    if row.category_id is None:
        return "unmapped"
    category = session.get(CashCategory, row.category_id)
    if category is None or category.cash_flow_section not in SECTIONS:
        return "unmapped"
    return category.cash_flow_section


def group_cashflow_payload(session: Session, companies: list, at: datetime, period) -> dict:
    date_from, date_to = period
    company_ids = {company.id for company in companies}
    incoming = {code: Decimal("0") for code in SECTIONS}
    outgoing = {code: Decimal("0") for code in SECTIONS}
    excluded: list[str] = []
    if companies:
        rows = list(
            session.scalars(
                select(CashTransaction).where(
                    CashTransaction.tenant_id == companies[0].tenant_id,
                    CashTransaction.company_id.in_(company_ids),
                    CashTransaction.status == "posted",
                    CashTransaction.business_date >= date_from,
                    CashTransaction.business_date <= date_to,
                )
            ).all()
        )
        for row in rows:
            if _internal(session, row):
                continue
            if _paired_inside(session, row, company_ids):
                token = str(row.transfer_group_id)
                if token not in excluded:
                    excluded.append(token)
                continue
            section = _section(session, row)
            if row.direction == "in":
                incoming[section] += row.amount
            else:
                outgoing[section] += row.amount
    external_in = sum(incoming.values(), Decimal("0"))
    external_out = sum(outgoing.values(), Decimal("0"))
    return {
        "as_of": at.isoformat(),
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "scope_company_ids": [str(company.id) for company in companies],
        "excluded_transfer_ids": excluded,
        "external_in": money_str(external_in),
        "external_out": money_str(external_out),
        "net_external": money_str(money(external_in - external_out)),
        "sections": [
            {"code": code, "in": money_str(incoming[code]), "out": money_str(outgoing[code])}
            for code in SECTIONS
        ],
    }


def _paired_inside(session: Session, row: CashTransaction, company_ids: set[uuid.UUID]) -> bool:
    if row.transfer_group_id is None:
        return False
    group = session.get(TransferGroup, row.transfer_group_id)
    if group is None or group.kind != "intercompany" or group.status != "linked":
        return False
    present = set(
        session.scalars(
            select(CashTransaction.company_id).where(
                CashTransaction.transfer_group_id == group.id
            )
        ).all()
    )
    return len(present) >= 2 and present <= company_ids


def _internal(session: Session, row: CashTransaction) -> bool:
    if row.transfer_group_id is None:
        return False
    group = session.get(TransferGroup, row.transfer_group_id)
    return group is not None and group.kind == "internal" and group.status == "linked"


def _missing_anchor(session: Session, wallet: Wallet) -> bool:
    from app.models.cash import OpeningBalance

    opening = session.scalar(
        select(OpeningBalance.id).where(
            OpeningBalance.wallet_id == wallet.id,
            OpeningBalance.status == "active",
        )
    )
    return opening is None
