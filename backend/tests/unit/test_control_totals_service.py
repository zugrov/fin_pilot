"""Unit: control totals invariants (FA-R02.4)."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.errors import AppError
from app.services.control_totals_service import (
    _cash_totals,
    compare_totals,
    validate_claim_fields,
)


def _cash_row(
    *,
    amount: str = "100.00",
    direction: str = "in",
    currency: str = "RUB",
    duplicate_status: str = "new",
    validation_errors: list | None = None,
    operation: str = "upsert",
):
    return SimpleNamespace(
        operation=operation,
        duplicate_status=duplicate_status,
        validation_errors=validation_errors or [],
        normalized_payload={
            "values": {
                "amount": amount,
                "direction": direction,
                "currency": currency,
                "business_date": "2026-10-05",
            }
        },
    )


def test_cash_invalid_row_makes_totals_unverifiable() -> None:
    row_ok = _cash_row(amount="100.00")
    row_bad = _cash_row(amount="", validation_errors=["bad_amount"])
    totals, ok = _cash_totals([row_ok, row_bad])
    assert totals is None
    assert ok is False


def test_cash_malformed_amount_unverifiable() -> None:
    row = _cash_row(amount="not-a-number")
    totals, ok = _cash_totals([row])
    assert totals is None
    assert ok is False


def test_cash_unsupported_currency() -> None:
    row = _cash_row(currency="USD")
    totals, ok = _cash_totals([row])
    assert totals is None
    assert ok is False


def test_compare_totals_uses_decimal_not_string_format() -> None:
    claim = {
        "record_count": 1,
        "currency": "RUB",
        "cash_in": "100.0",
        "cash_out": "0.00",
    }
    calculated = {
        "record_count": 1,
        "currency": "RUB",
        "cash_in": "100.00",
        "cash_out": "0.00",
    }
    assert compare_totals(claim, calculated, "cash") is True


def test_validate_claim_rejects_extra_fields() -> None:
    with pytest.raises(AppError) as exc:
        validate_claim_fields(
            {"record_count": 1, "currency": "RUB", "cash_in": "1", "cash_out": "0", "extra": "x"},
            "cash",
        )
    assert exc.value.status_code == 422


def test_unpost_counts_but_not_summed() -> None:
    row = _cash_row(operation="unpost", amount="999.00")
    totals, ok = _cash_totals([row])
    assert ok is True
    assert totals is not None
    assert totals["record_count"] == 1
    assert Decimal(totals["cash_in"]) == Decimal("0.00")
