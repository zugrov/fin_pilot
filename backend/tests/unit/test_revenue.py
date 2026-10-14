from datetime import date
from decimal import Decimal

from app.domain.imports.revenue_reader import read_revenue_csv
from app.domain.revenue import NO_REVENUE_LABEL, SaleFact, assess_revenue


def test_revenue_is_unavailable_without_coverage() -> None:
    view = assess_revenue((), covered=False)
    assert view.amount is None
    assert view.label == NO_REVENUE_LABEL
    assert "missing_revenue_source" in view.quality_flags


def test_zero_revenue_needs_full_coverage() -> None:
    view = assess_revenue((), covered=True)
    assert view.amount == Decimal("0.00")
    assert view.metric_basis == "net"


def test_net_revenue_subtracts_returns() -> None:
    view = assess_revenue(
        (
            SaleFact("a", "sale", "net", Decimal("100000.00"), Decimal("120000.00")),
            SaleFact("b", "return", "net", Decimal("10000.00"), Decimal("12000.00")),
        ),
        covered=True,
    )
    assert view.amount == Decimal("90000.00")
    assert view.entry_ids == ("a", "b")


def test_unknown_vat_is_not_net_revenue() -> None:
    view = assess_revenue(
        (SaleFact("a", "sale", "unknown", None, Decimal("120000.00")),),
        covered=True,
    )
    assert view.metric_basis == "source"
    assert view.amount == Decimal("120000.00")
    assert "vat_basis_unknown" in view.quality_flags


def test_revenue_csv_rejects_cash_header() -> None:
    content = (
        b"external_id,wallet_code,business_date,direction,amount,currency,"
        b"counterparty_inn,counterparty_name,description,document_number,"
        b"category_code,direction_code\n"
    )
    try:
        read_revenue_csv(content, encoding="utf-8", max_rows=10, vat_basis="net")
    except Exception as exc:
        assert exc.code == "unsupported_format"
    else:
        raise AssertionError("денежный файл должен быть отклонён")


def test_revenue_csv_reads_sale() -> None:
    content = (
        b"external_id,recognition_date,document_number,counterparty_inn,"
        b"amount_ex_vat,vat_amount,amount_inc_vat,entry_type,direction_code\n"
        b"sale-1,2026-10-10,15,,100000.00,20000.00,120000.00,sale,\n"
    )
    lines = read_revenue_csv(content, encoding="utf-8", max_rows=10, vat_basis="net")
    assert lines[0].recognition_date == date(2026, 10, 10)
    assert lines[0].amount_ex_vat == Decimal("100000.00")
    assert lines[0].errors == ()
