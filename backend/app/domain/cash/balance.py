from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.domain.billing.periods import MOSCOW
from app.domain.money import money

MISSING_ANCHOR = "missing_anchor"
INTRADAY = "intraday_approximation"
MISSING_REVENUE = "missing_revenue_source"


@dataclass(frozen=True)
class CashLine:
    direction: str
    amount: Decimal
    status: str
    business_date: date
    occurred_at: datetime | None
    transfer_kind: str | None
    category_section: str | None


@dataclass(frozen=True)
class Anchor:
    effective_at: datetime
    amount: Decimal


@dataclass(frozen=True)
class WalletInput:
    anchor: Anchor | None
    availability_type: str
    available_from: datetime | None
    minimum_reserve: Decimal
    lines: tuple[CashLine, ...]


@dataclass(frozen=True)
class MoneyView:
    amount: Decimal | None
    quality_flags: tuple[str, ...]


def line_moment(line: CashLine, tz: ZoneInfo = MOSCOW) -> tuple[datetime, bool]:
    if line.occurred_at is not None:
        return line.occurred_at, False
    end = datetime.combine(line.business_date, time.max, tzinfo=tz)
    return end, True


def wallet_balance(wallet: WalletInput, at: datetime) -> MoneyView:
    if wallet.anchor is None:
        return MoneyView(None, (MISSING_ANCHOR,))
    total = wallet.anchor.amount
    flags: list[str] = []
    for line in wallet.lines:
        if line.status != "posted":
            continue
        moment, approximate = line_moment(line)
        if moment < wallet.anchor.effective_at or moment > at:
            continue
        if approximate and INTRADAY not in flags:
            flags.append(INTRADAY)
        signed = line.amount if line.direction == "in" else -line.amount
        total += signed
    return MoneyView(money(total), tuple(flags))


def is_spendable(wallet: WalletInput, at: datetime) -> bool:
    if wallet.availability_type == "spendable":
        return True
    if wallet.available_from is None:
        return False
    return wallet.available_from <= at
