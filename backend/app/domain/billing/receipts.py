from dataclasses import dataclass
from decimal import Decimal

from app.domain.billing.pricing import (
    ADDITIONAL_COMPANY,
    FIRST_COMPANY,
    discount_factor,
)
from app.domain.money import money


@dataclass(frozen=True)
class ReceiptLine:
    description: str
    quantity: int
    discounted_unit_price: Decimal
    amount: Decimal


def build_package_lines(
    *,
    companies: int,
    interval: str,
    payable: Decimal,
    discount_percent: Decimal,
) -> list[ReceiptLine]:
    if companies < 1:
        raise ValueError("нужна хотя бы одна фирма")
    if interval == "month":
        prices = [FIRST_COMPANY, *([ADDITIONAL_COMPANY] * (companies - 1))]
        label = "месяц"
    elif interval == "year":
        factor = discount_factor(discount_percent)
        first = money(FIRST_COMPANY * 12 * factor)
        extra = money(ADDITIONAL_COMPANY * 12 * factor)
        prices = [first, *([extra] * (companies - 1))]
        label = "год"
    else:
        raise ValueError("неизвестный интервал")

    drift = payable - sum(prices, Decimal("0.00"))
    prices[-1] = money(prices[-1] + drift)
    if any(price < 0 for price in prices):
        raise ValueError("отрицательная строка чека запрещена")

    lines = [
        ReceiptLine(
            description=f"Подписка, {label}, фирма {index}",
            quantity=1,
            discounted_unit_price=price,
            amount=price,
        )
        for index, price in enumerate(prices, start=1)
    ]
    total = sum((line.amount for line in lines), Decimal("0.00"))
    if total != payable:
        raise ValueError("сумма строк чека не равна платежу")
    return lines


def build_upgrade_line(*, description: str, payable: Decimal) -> list[ReceiptLine]:
    if payable < 0:
        raise ValueError("отрицательная строка чека запрещена")
    return [
        ReceiptLine(
            description=description,
            quantity=1,
            discounted_unit_price=payable,
            amount=payable,
        )
    ]
