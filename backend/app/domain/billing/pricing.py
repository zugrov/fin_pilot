from decimal import Decimal

from app.domain.money import money

FIRST_COMPANY = Decimal("2500.00")
ADDITIONAL_COMPANY = Decimal("1500.00")
APPROVED_ANNUAL_DISCOUNT_PERCENT = Decimal("15.00")
MIN_CHARGE = Decimal("1.00")


def discount_factor(discount_percent: Decimal) -> Decimal:
    return (Decimal("100") - discount_percent) / Decimal("100")


def monthly_price(companies: int) -> Decimal:
    if companies < 1:
        raise ValueError("нужна хотя бы одна фирма")
    return money(FIRST_COMPANY + ADDITIONAL_COMPANY * (companies - 1))


def annual_list_price(companies: int) -> Decimal:
    return money(monthly_price(companies) * 12)


def annual_payable(
    companies: int,
    discount_percent: Decimal = APPROVED_ANNUAL_DISCOUNT_PERCENT,
) -> Decimal:
    return money(annual_list_price(companies) * discount_factor(discount_percent))


def annual_savings(
    companies: int,
    discount_percent: Decimal = APPROVED_ANNUAL_DISCOUNT_PERCENT,
) -> Decimal:
    return money(annual_list_price(companies) - annual_payable(companies, discount_percent))


def monthly_equivalent(
    companies: int,
    discount_percent: Decimal = APPROVED_ANNUAL_DISCOUNT_PERCENT,
) -> Decimal:
    return money(annual_payable(companies, discount_percent) / Decimal(12))


def package_price(
    companies: int,
    interval: str,
    discount_percent: Decimal = APPROVED_ANNUAL_DISCOUNT_PERCENT,
) -> tuple[Decimal, Decimal, Decimal]:
    """Список, скидка и сумма к оплате для полного периода."""
    if interval == "month":
        list_amount = monthly_price(companies)
        return list_amount, Decimal("0.00"), list_amount
    if interval != "year":
        raise ValueError("неизвестный интервал")
    list_amount = annual_list_price(companies)
    payable = annual_payable(companies, discount_percent)
    return list_amount, money(list_amount - payable), payable


def additional_full_period(interval: str, discount_percent: Decimal) -> Decimal:
    if interval == "month":
        return ADDITIONAL_COMPANY
    if interval != "year":
        raise ValueError("неизвестный интервал")
    return money(ADDITIONAL_COMPANY * 12 * discount_factor(discount_percent))
