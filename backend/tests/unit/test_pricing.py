from decimal import Decimal

import pytest
from app.domain.billing.pricing import (
    annual_list_price,
    annual_payable,
    annual_savings,
    monthly_equivalent,
    monthly_price,
    package_price,
)
from app.domain.billing.receipts import build_package_lines, build_upgrade_line
from app.domain.billing.upgrade import upgrade_amount

PAY1 = {1: "2500.00", 2: "4000.00", 3: "5500.00", 5: "8500.00"}
YEAR1 = {1: "25500.00", 2: "40800.00", 3: "56100.00", 5: "86700.00"}


@pytest.mark.parametrize("companies,expected", PAY1.items())
def test_pay1_monthly_price(companies: int, expected: str) -> None:
    assert monthly_price(companies) == Decimal(expected)


@pytest.mark.parametrize("companies,expected", YEAR1.items())
def test_year1_annual_payable(companies: int, expected: str) -> None:
    assert annual_payable(companies) == Decimal(expected)
    assert annual_savings(companies) == annual_list_price(companies) - Decimal(expected)


def test_year1_table_matches_spec() -> None:
    assert monthly_equivalent(1) == Decimal("2125.00")
    assert monthly_equivalent(2) == Decimal("3400.00")
    assert monthly_equivalent(3) == Decimal("4675.00")
    assert annual_list_price(1) == Decimal("30000.00")
    assert annual_savings(2) == Decimal("7200.00")


def test_year5_additional_company_half_period() -> None:
    full = upgrade_amount(
        interval="year",
        added_slots=1,
        remaining_seconds=100,
        period_seconds=100,
        discount_percent=Decimal("15.00"),
    )
    half = upgrade_amount(
        interval="year",
        added_slots=1,
        remaining_seconds=50,
        period_seconds=100,
        discount_percent=Decimal("15.00"),
    )
    assert full == Decimal("15300.00")
    assert half == Decimal("7650.00")


def test_monthly_upgrade_uses_1500() -> None:
    amount = upgrade_amount(
        interval="month",
        added_slots=2,
        remaining_seconds=1,
        period_seconds=2,
        discount_percent=Decimal("15.00"),
    )
    assert amount == Decimal("1500.00")


def test_upgrade_below_one_ruble_is_deferred() -> None:
    amount = upgrade_amount(
        interval="month",
        added_slots=1,
        remaining_seconds=1,
        period_seconds=10_000_000,
        discount_percent=Decimal("15.00"),
    )
    assert amount is None


def test_year11_receipt_lines_equal_payable() -> None:
    for companies in (1, 2, 3, 5):
        payable = annual_payable(companies)
        lines = build_package_lines(
            companies=companies,
            interval="year",
            payable=payable,
            discount_percent=Decimal("15.00"),
        )
        assert sum(line.amount for line in lines) == payable
        assert all(line.amount > 0 for line in lines)


def test_receipt_has_no_negative_discount_line() -> None:
    lines = build_upgrade_line(description="Доплата", payable=Decimal("7650.00"))
    assert len(lines) == 1
    assert lines[0].amount == Decimal("7650.00")


def test_client_discount_is_not_a_pricing_input() -> None:
    list_amount, discount, payable = package_price(2, "year", Decimal("15.00"))
    assert list_amount == Decimal("48000.00")
    assert discount == Decimal("7200.00")
    assert payable == Decimal("40800.00")


def test_zero_companies_rejected() -> None:
    with pytest.raises(ValueError):
        monthly_price(0)
