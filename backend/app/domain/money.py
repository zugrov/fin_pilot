from decimal import ROUND_HALF_UP, Decimal

MONEY_QUANTUM = Decimal("0.01")
PERCENT_QUANTUM = Decimal("0.000001")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def percent(value: Decimal) -> Decimal:
    return value.quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP)


def money_str(value: Decimal) -> str:
    return format(money(value), "f")
