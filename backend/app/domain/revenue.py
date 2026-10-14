import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal

from app.domain.money import money

NO_REVENUE_LABEL = "Нет данных о выручке"
NET_LABEL = "Выручка без НДС"
SOURCE_LABEL = "сумма продаж по данным источника"
GROUP_REVENUE_LABEL = "Сумма выручки фирм до исключения внутригрупповых продаж"


@dataclass(frozen=True)
class SaleFact:
    entry_id: str
    entry_type: str
    vat_basis: str
    amount_ex_vat: Decimal | None
    amount_inc_vat: Decimal


@dataclass(frozen=True)
class RevenueView:
    amount: Decimal | None
    label: str
    metric_basis: str
    quality_flags: tuple[str, ...]
    entry_ids: tuple[str, ...]


def assess_revenue(entries: tuple[SaleFact, ...], *, covered: bool) -> RevenueView:
    ids = tuple(item.entry_id for item in entries)
    if not entries and not covered:
        return RevenueView(None, NO_REVENUE_LABEL, "unavailable", ("missing_revenue_source",), ())
    if not entries and covered:
        return RevenueView(Decimal("0.00"), NET_LABEL, "net", (), ())
    flags: list[str] = []
    if not covered:
        flags.append("partial_period")
    unknown = any(item.vat_basis != "net" or item.amount_ex_vat is None for item in entries)
    if unknown:
        flags.append("vat_basis_unknown")
        return RevenueView(
            _signed(entries, gross=True),
            SOURCE_LABEL,
            "source",
            tuple(flags),
            ids,
        )
    return RevenueView(_signed(entries, gross=False), NET_LABEL, "net", tuple(flags), ids)


def _signed(entries: tuple[SaleFact, ...], *, gross: bool) -> Decimal:
    total = Decimal("0")
    for item in entries:
        amount = item.amount_inc_vat if gross else item.amount_ex_vat
        if amount is None:
            continue
        if item.entry_type == "return":
            total -= amount
        else:
            total += amount
    return money(total)


def input_revision(parts: dict[str, str]) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
