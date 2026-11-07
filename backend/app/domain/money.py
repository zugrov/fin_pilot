from decimal import ROUND_HALF_UP, Decimal

MONEY_QUANTUM = Decimal("0.01")
PERCENT_QUANTUM = Decimal("0.000001")
SCALE_6_QUANTUM = Decimal("0.000001")
SCALE_8_QUANTUM = Decimal("0.00000001")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY_QUANTUM, rounding=ROUND_HALF_UP)


def percent(value: Decimal) -> Decimal:
    return value.quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP)


def money_str(value: Decimal) -> str:
    return format(money(value), "f")


def numeric_scale_6(value: Decimal) -> Decimal:
    """Шкала дефлятора и иных коэффициентов (6 знаков после запятой, ROUND_HALF_UP)."""
    return value.quantize(SCALE_6_QUANTUM, rounding=ROUND_HALF_UP)


def numeric_scale_6_str(value: Decimal) -> str:
    return format(numeric_scale_6(value), "f")


def vat_rate_fraction(value: Decimal) -> Decimal:
    """Расчётная доля НДС в цене (мин. 8 знаков, ROUND_HALF_UP — как у money)."""
    return value.quantize(SCALE_8_QUANTUM, rounding=ROUND_HALF_UP)


def vat_rate_fraction_str(value: Decimal) -> str:
    return format(vat_rate_fraction(value), "f")
