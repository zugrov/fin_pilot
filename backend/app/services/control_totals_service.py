"""Control totals: расчёт по distinct batch_id (FA-R02.4)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.imports import ImportBatch, RawImportRow, SourceConnection
from sqlalchemy import select
from sqlalchemy.orm import Session

MONEY_FIELDS = frozenset({"cash_in", "cash_out", "revenue_net"})
SUPPORTED_CURRENCIES = frozenset({"RUB"})
CASH_REQUIRED_CLAIM = frozenset({"record_count", "currency", "cash_in", "cash_out"})
REVENUE_REQUIRED_CLAIM = frozenset({"record_count", "currency", "revenue_net"})
COUNT_ONLY_REQUIRED = frozenset({"record_count"})


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if not amount.is_finite():
        return None
    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        return None
    return amount.quantize(Decimal("0.01"))


def _money_string(amount: Decimal) -> str:
    return format(amount.quantize(Decimal("0.01")), "f")


def _row_record_count(rows: list[RawImportRow]) -> int:
    return len(rows)


def _cash_row_needs_amount(row: RawImportRow) -> bool:
    if row.operation == "unpost":
        return False
    if row.duplicate_status == "invalid":
        return False
    return True


def _cash_totals(rows: list[RawImportRow]) -> tuple[dict[str, Any] | None, bool]:
    cash_in = Decimal("0.00")
    cash_out = Decimal("0.00")
    currency: str | None = None
    verifiable = True
    for row in rows:
        if row.operation == "unpost":
            continue
        if row.duplicate_status == "invalid" or row.validation_errors:
            if row.operation != "unpost":
                verifiable = False
            continue
        data = row.normalized_payload
        if not data:
            verifiable = False
            continue
        values = data.get("values") or {}
        direction = values.get("direction")
        amount_raw = values.get("amount")
        row_currency = (values.get("currency") or "").strip()
        if not row_currency:
            verifiable = False
            continue
        if row_currency not in SUPPORTED_CURRENCIES:
            return None, False
        if direction not in {"in", "out"} or amount_raw is None or str(amount_raw).strip() == "":
            verifiable = False
            continue
        amount = _parse_decimal(amount_raw)
        if amount is None:
            verifiable = False
            continue
        if currency is None:
            currency = row_currency
        elif currency != row_currency:
            return None, False
        if direction == "in":
            cash_in += amount
        else:
            cash_out += amount
    if not verifiable:
        return None, False
    return {
        "record_count": _row_record_count(rows),
        "cash_in": _money_string(cash_in),
        "cash_out": _money_string(cash_out),
        "currency": currency,
    }, True


def _revenue_totals(rows: list[RawImportRow]) -> tuple[dict[str, Any] | None, bool]:
    revenue_net = Decimal("0.00")
    currency: str | None = None
    verifiable = True
    for row in rows:
        if row.operation == "unpost":
            continue
        if row.duplicate_status == "invalid" or row.validation_errors:
            if row.operation != "unpost":
                verifiable = False
            continue
        data = row.normalized_payload
        if not data:
            verifiable = False
            continue
        values = data.get("values") or {}
        amount_raw = values.get("amount_ex_vat")
        row_currency = (values.get("currency") or "RUB").strip()
        if row_currency not in SUPPORTED_CURRENCIES:
            return None, False
        if amount_raw is None or str(amount_raw).strip() == "":
            verifiable = False
            continue
        amount = _parse_decimal(amount_raw)
        if amount is None:
            verifiable = False
            continue
        if currency is None:
            currency = row_currency
        elif currency != row_currency:
            return None, False
        revenue_net += amount
    if not verifiable:
        return None, False
    return {
        "record_count": _row_record_count(rows),
        "revenue_net": _money_string(revenue_net),
        "currency": currency,
    }, True


def _count_only_totals(rows: list[RawImportRow]) -> dict[str, Any]:
    return {"record_count": _row_record_count(rows)}


def calculate_batch_totals(
    session: Session, batch: ImportBatch, connection: SourceConnection
) -> tuple[dict[str, Any] | None, bool]:
    rows = session.scalars(
        select(RawImportRow)
        .where(RawImportRow.batch_id == batch.id)
        .order_by(RawImportRow.row_number)
    ).all()
    dataset = connection.dataset
    if dataset == "cash":
        return _cash_totals(list(rows))
    if dataset == "revenue":
        return _revenue_totals(list(rows))
    return _count_only_totals(list(rows)), True


def aggregate_delivery_totals(
    session: Session,
    batch_ids: list[uuid.UUID],
    connection: SourceConnection,
) -> tuple[dict[str, Any] | None, bool]:
    unique_ids = list(dict.fromkeys(batch_ids))
    if not unique_ids:
        return {"record_count": 0}, True
    per_batch: list[dict[str, Any] | None] = []
    verifiable = True
    for batch_id in unique_ids:
        batch = session.get(ImportBatch, batch_id)
        if batch is None:
            verifiable = False
            continue
        totals, ok = calculate_batch_totals(session, batch, connection)
        if not ok:
            verifiable = False
        per_batch.append(totals)
    if not verifiable:
        return None, False
    record_count = sum(int(item.get("record_count", 0)) for item in per_batch if item)
    merged: dict[str, Any] = {
        "record_count": record_count,
        "batch_ids": [str(i) for i in unique_ids],
    }
    dataset = connection.dataset
    if dataset == "cash":
        cash_in = Decimal("0.00")
        cash_out = Decimal("0.00")
        currency: str | None = None
        for item in per_batch:
            if not item:
                continue
            if currency is None:
                currency = item.get("currency")
            cash_in += _parse_decimal(item.get("cash_in")) or Decimal("0.00")
            cash_out += _parse_decimal(item.get("cash_out")) or Decimal("0.00")
        merged["cash_in"] = _money_string(cash_in)
        merged["cash_out"] = _money_string(cash_out)
        merged["currency"] = currency
    elif dataset == "revenue":
        revenue_net = Decimal("0.00")
        currency = None
        for item in per_batch:
            if not item:
                continue
            if currency is None:
                currency = item.get("currency")
            revenue_net += _parse_decimal(item.get("revenue_net")) or Decimal("0.00")
        merged["revenue_net"] = _money_string(revenue_net)
        merged["currency"] = currency
    return merged, True


def validate_claim_fields(claim: dict[str, Any], dataset: str) -> None:
    from app.errors import AppError

    allowed = COUNT_ONLY_REQUIRED | MONEY_FIELDS | {"currency"}
    extra = set(claim) - allowed
    if extra:
        raise AppError(
            422,
            "validation_error",
            f"Неподдерживаемые поля control_totals: {', '.join(sorted(extra))}",
        )
    if dataset == "cash":
        missing = CASH_REQUIRED_CLAIM - set(claim)
        if missing:
            raise AppError(
                422,
                "validation_error",
                f"Не хватает полей control_totals: {', '.join(sorted(missing))}",
            )
    elif dataset == "revenue":
        missing = REVENUE_REQUIRED_CLAIM - set(claim)
        if missing:
            raise AppError(
                422,
                "validation_error",
                f"Не хватает полей control_totals: {', '.join(sorted(missing))}",
            )
    elif dataset in {"plan", "budget", "balances"}:
        missing = COUNT_ONLY_REQUIRED - set(claim)
        if missing:
            raise AppError(
                422,
                "validation_error",
                "Не хватает record_count в control_totals",
            )
        money_in_claim = MONEY_FIELDS & set(claim)
        if money_in_claim:
            raise AppError(
                422,
                "validation_error",
                "Денежные control_totals недоступны для этого dataset",
            )
    currency = claim.get("currency")
    if currency is not None and currency not in SUPPORTED_CURRENCIES:
        raise AppError(422, "validation_error", "Неподдерживаемая валюта control_totals")


def _decimal_field_equal(claim_val: Any, calculated_val: Any) -> bool:
    left = _parse_decimal(claim_val)
    right = _parse_decimal(calculated_val)
    if left is None or right is None:
        return False
    return left == right


def compare_totals(claim: dict[str, Any], calculated: dict[str, Any], dataset: str) -> bool:
    if int(claim.get("record_count", -1)) != int(calculated.get("record_count", -2)):
        return False
    if dataset == "cash":
        return (
            _decimal_field_equal(claim.get("cash_in"), calculated.get("cash_in"))
            and _decimal_field_equal(claim.get("cash_out"), calculated.get("cash_out"))
            and claim.get("currency") == calculated.get("currency")
        )
    if dataset == "revenue":
        return (
            _decimal_field_equal(claim.get("revenue_net"), calculated.get("revenue_net"))
            and claim.get("currency") == calculated.get("currency")
        )
    return True


def row_business_date(row: RawImportRow, dataset: str) -> date | None:
    if row.operation == "unpost":
        return None
    data = row.normalized_payload or {}
    values = data.get("values") or {}
    key = "recognition_date" if dataset == "revenue" else "business_date"
    raw = values.get(key)
    if not raw or not str(raw).strip():
        return None
    try:
        return date.fromisoformat(str(raw).strip())
    except ValueError:
        return None


def batches_rows_within_period(
    session: Session,
    batch_ids: list[uuid.UUID],
    dataset: str,
    period_from: date,
    period_to: date,
) -> bool:
    unique_ids = list(dict.fromkeys(batch_ids))
    for batch_id in unique_ids:
        rows = session.scalars(
            select(RawImportRow).where(RawImportRow.batch_id == batch_id)
        ).all()
        for row in rows:
            moment = row_business_date(row, dataset)
            if moment is None:
                if row.operation == "unpost":
                    continue
                return False
            if moment < period_from or moment > period_to:
                return False
    return True
