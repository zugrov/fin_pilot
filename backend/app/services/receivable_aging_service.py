"""FA-R06.1-P3b: возрастной анализ дебиторки (read-only, без миграций)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.domain.money import money, money_str
from app.models.cash import CashTransaction
from app.models.imports import SourceConnection
from app.models.revenue import Counterparty, RevenueCashMatch, RevenueEntry
from app.services.cash_service import revenue_allocated_on_cash
from app.services.report_service import _coverage, _internal, _section
from sqlalchemy import func, select
from sqlalchemy.orm import Session

BUCKETS = ("0-30", "31-60", "61-90", ">90")
UNALLOCATED_SECTIONS = frozenset({"operating", "unmapped"})


def default_as_of(at: datetime, timezone: str) -> date:
    return at.astimezone(ZoneInfo(timezone or "Europe/Moscow")).date()


def receivable_aging_payload(
    session: Session,
    company,
    *,
    as_of: date,
    max_rows: int,
) -> dict:
    flags: list[str] = []
    completeness = _receivable_completeness(session, company, as_of, flags)
    sales = list(
        session.scalars(
            select(RevenueEntry).where(
                RevenueEntry.tenant_id == company.tenant_id,
                RevenueEntry.company_id == company.id,
                RevenueEntry.status == "posted",
                RevenueEntry.entry_type == "sale",
                RevenueEntry.recognition_date <= as_of,
            )
        ).all()
    )
    returns = list(
        session.scalars(
            select(RevenueEntry).where(
                RevenueEntry.tenant_id == company.tenant_id,
                RevenueEntry.company_id == company.id,
                RevenueEntry.status == "posted",
                RevenueEntry.entry_type == "return",
                RevenueEntry.recognition_date <= as_of,
            )
        ).all()
    )
    sale_by_id = {row.id: row for row in sales}
    linked_returns_by_sale: dict[uuid.UUID, list[RevenueEntry]] = {}
    rows: list[dict] = []

    for ret in returns:
        sale_id = ret.linked_sale_entry_id
        if sale_id is None:
            rows.append(_orphan_return_row(session, ret, as_of, flags))
            continue
        sale = sale_by_id.get(sale_id) or session.get(RevenueEntry, sale_id)
        if sale is None or sale.status != "posted" or sale.entry_type != "sale":
            rows.append(_orphan_return_row(session, ret, as_of, flags))
            continue
        linked_returns_by_sale.setdefault(sale_id, []).append(ret)

    for sale in sales:
        linked = linked_returns_by_sale.get(sale.id, [])
        matched = _matched_as_of(session, sale.id, as_of)
        linked_amounts = (item.amount_inc_vat for item in linked if item.recognition_date <= as_of)
        return_sum = money(sum(linked_amounts, Decimal("0")))
        balance = money(sale.amount_inc_vat - matched - return_sum)
        if balance == 0:
            continue
        rows.append(_sale_row(session, sale, balance, as_of, flags))

    rows.sort(key=lambda item: (item["recognition_date"], item["document"]["external_id"] or ""))
    rows_truncated = len(rows) > max_rows
    if rows_truncated:
        rows = rows[:max_rows]

    totals_by_bucket = {code: Decimal("0") for code in BUCKETS}
    totals_by_cp: dict[str | None, Decimal] = {}
    total_balance = Decimal("0")
    for row in rows:
        if row.get("orphan_return"):
            bal = Decimal(row["balance"])
        else:
            bal = Decimal(row["balance"])
        total_balance = money(total_balance + bal)
        bucket = row["bucket"]
        totals_by_bucket[bucket] = money(totals_by_bucket[bucket] + bal)
        inn = row["counterparty"]["inn"] if row["counterparty"] else None
        totals_by_cp[inn] = money(totals_by_cp.get(inn, Decimal("0")) + bal)

    unallocated = _unallocated_receipts(session, company, as_of)
    cp_rows = [
        {
            "inn": inn,
            "name": _counterparty_name(session, company, inn),
            "balance": money_str(amount),
        }
        for inn, amount in sorted(totals_by_cp.items(), key=lambda item: (item[0] or "", item[1]))
    ]

    return {
        "company_id": str(company.id),
        "as_of": as_of.isoformat(),
        "completeness": completeness,
        "quality_flags": flags,
        "total_balance": money_str(total_balance),
        "totals_by_bucket": {key: money_str(totals_by_bucket[key]) for key in BUCKETS},
        "totals_by_counterparty": cp_rows,
        "unallocated_receipts": unallocated,
        "rows": rows,
        "rows_truncated": rows_truncated,
    }


def _sale_row(
    session: Session,
    sale: RevenueEntry,
    balance: Decimal,
    as_of: date,
    flags: list[str],
) -> dict:
    if sale.counterparty_id is None and "missing_counterparty" not in flags:
        flags.append("missing_counterparty")
    age_days = (as_of - sale.recognition_date).days
    return {
        "recognition_date": sale.recognition_date.isoformat(),
        "counterparty": _counterparty_payload(session, sale.counterparty_id),
        "document": {
            "number": sale.document_number,
            "external_id": sale.external_id,
        },
        "balance": money_str(balance),
        "bucket": _bucket(age_days),
        "age_days": age_days,
        "orphan_return": False,
    }


def _orphan_return_row(
    session: Session,
    ret: RevenueEntry,
    as_of: date,
    flags: list[str],
) -> dict:
    if ret.counterparty_id is None and "missing_counterparty" not in flags:
        flags.append("missing_counterparty")
    age_days = (as_of - ret.recognition_date).days
    return {
        "recognition_date": ret.recognition_date.isoformat(),
        "counterparty": _counterparty_payload(session, ret.counterparty_id),
        "document": {
            "number": ret.document_number,
            "external_id": ret.external_id,
        },
        "balance": money_str(-ret.amount_inc_vat),
        "bucket": _bucket(age_days),
        "age_days": age_days,
        "orphan_return": True,
    }


def _counterparty_payload(session: Session, counterparty_id: uuid.UUID | None) -> dict | None:
    if counterparty_id is None:
        return None
    party = session.get(Counterparty, counterparty_id)
    if party is None:
        return None
    return {"inn": party.inn, "name": party.name}


def _counterparty_name(session: Session, company, inn: str | None) -> str | None:
    if inn is None:
        return None
    party = session.scalar(
        select(Counterparty).where(
            Counterparty.tenant_id == company.tenant_id,
            Counterparty.company_id == company.id,
            Counterparty.inn == inn,
        )
    )
    return None if party is None else party.name


def _bucket(age_days: int) -> str:
    if age_days <= 30:
        return "0-30"
    if age_days <= 60:
        return "31-60"
    if age_days <= 90:
        return "61-90"
    return ">90"


def _matched_as_of(session: Session, revenue_entry_id: uuid.UUID, as_of: date) -> Decimal:
    value = session.scalar(
        select(func.coalesce(func.sum(RevenueCashMatch.amount), 0))
        .join(CashTransaction, RevenueCashMatch.cash_transaction_id == CashTransaction.id)
        .where(
            RevenueCashMatch.revenue_entry_id == revenue_entry_id,
            CashTransaction.business_date <= as_of,
            CashTransaction.status == "posted",
        )
    )
    if not isinstance(value, Decimal):
        return Decimal("0")
    return money(value)


def _unallocated_receipts(session: Session, company, as_of: date) -> list[dict]:
    rows = list(
        session.scalars(
            select(CashTransaction).where(
                CashTransaction.tenant_id == company.tenant_id,
                CashTransaction.company_id == company.id,
                CashTransaction.status == "posted",
                CashTransaction.direction == "in",
                CashTransaction.business_date <= as_of,
            )
        ).all()
    )
    items: list[dict] = []
    for row in rows:
        if _internal(session, row):
            continue
        section = _section(session, row)
        if section not in UNALLOCATED_SECTIONS:
            continue
        allocated = revenue_allocated_on_cash(session, row.id)
        remainder = money(row.amount - allocated)
        if remainder <= 0:
            continue
        doc = (row.document_number or "").strip()
        if doc.startswith("RD-OVER"):
            continue
        items.append(
            {
                "cash_transaction_id": str(row.id),
                "document_number": row.document_number,
                "business_date": row.business_date.isoformat(),
                "amount": money_str(remainder),
                "label": row.description or "поступление",
            }
        )
    return items


def _enabled_revenue_sources(session: Session, company) -> list[SourceConnection]:
    return list(
        session.scalars(
            select(SourceConnection).where(
                SourceConnection.tenant_id == company.tenant_id,
                SourceConnection.company_id == company.id,
                SourceConnection.dataset == "revenue",
                SourceConnection.enabled.is_(True),
            )
        ).all()
    )


def _receivable_completeness(
    session: Session,
    company,
    as_of: date,
    flags: list[str],
) -> str:
    sources = _enabled_revenue_sources(session, company)
    if not sources:
        if "missing_revenue_source" not in flags:
            flags.append("missing_revenue_source")
        return "unavailable"
    partial = False
    for source in sources:
        covered, _ = _coverage([source], as_of)
        if not covered:
            partial = True
            break
    if partial and "partial_period" not in flags:
        flags.append("partial_period")
        return "preliminary"
    return "full"
