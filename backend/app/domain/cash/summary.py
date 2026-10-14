from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.domain.cash.balance import (
    MISSING_ANCHOR,
    MISSING_REVENUE,
    WalletInput,
    is_spendable,
    line_moment,
    wallet_balance,
)
from app.domain.money import money


@dataclass(frozen=True)
class CashSummary:
    cash_total: Decimal | None
    available: Decimal | None
    restricted: Decimal | None
    headroom: Decimal | None
    external_in: Decimal | None
    external_out: Decimal | None
    financing_in: Decimal | None
    revenue: None
    quality_flags: tuple[str, ...]


def _posted_in_window(wallet: WalletInput, at: datetime) -> list:
    if wallet.anchor is None:
        return []
    chosen = []
    for line in wallet.lines:
        if line.status != "posted":
            continue
        moment, _approximate = line_moment(line)
        if wallet.anchor.effective_at <= moment <= at:
            chosen.append(line)
    return chosen


def summarize(wallets: tuple[WalletInput, ...], at: datetime, reserve: Decimal) -> CashSummary:
    flags: list[str] = [MISSING_REVENUE]
    if any(item.anchor is None for item in wallets):
        flags.append(MISSING_ANCHOR)
        return CashSummary(None, None, None, None, None, None, None, None, tuple(flags))
    total = Decimal("0")
    available = Decimal("0")
    restricted = Decimal("0")
    external_in = Decimal("0")
    external_out = Decimal("0")
    financing_in = Decimal("0")
    for wallet in wallets:
        view = wallet_balance(wallet, at)
        amount = view.amount or Decimal("0")
        for flag in view.quality_flags:
            if flag not in flags:
                flags.append(flag)
        total += amount
        if is_spendable(wallet, at):
            available += amount
        else:
            restricted += amount
        for line in _posted_in_window(wallet, at):
            if line.transfer_kind == "internal":
                continue
            if line.direction == "in":
                external_in += line.amount
                if line.category_section == "financing":
                    financing_in += line.amount
            else:
                external_out += line.amount
    headroom = available - reserve
    return CashSummary(
        money(total),
        money(available),
        money(restricted),
        money(headroom),
        money(external_in),
        money(external_out),
        money(financing_in),
        None,
        tuple(flags),
    )
