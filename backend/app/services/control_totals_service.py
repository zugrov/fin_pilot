"""Control totals: расчёт по distinct batch_id (FA-R02.4)."""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from app.models.imports import ImportBatch, RawImportRow, SourceConnection
from sqlalchemy import select
from sqlalchemy.orm import Session

MONEY_FIELDS = frozenset({"cash_in", "cash_out", "revenue_net"})
SUPPORTED_CURRENCIES = frozenset({"RUB"})


def _money(value: str) -> Decimal | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        return None
    return amount.quantize(Decimal("0.01"))


def _row_record_count(rows: list[RawImportRow]) -> int:
    return len(rows)


def _cash_totals(rows: list[RawImportRow]) -> tuple[dict[str, Any] | None, bool]:
    cash_in = Decimal("0.00")
    cash_out = Decimal("0.00")
    currency: str | None = None
    verifiable = True
    for row in rows:
        if row.operation == "unpost":
            continue
        data = row.normalized_payload
        if not data or row.validation_errors:
            if _needs_cash_amount(row):
                verifiable = False
            continue
        values = data.get("values") or {}
        direction = values.get("direction")
        amount_raw = values.get("amount")
        if direction not in {"in", "out"} or amount_raw is None:
            verifiable = False
            continue
        amount = _money(str(amount_raw))
        if amount is None:
            verifiable = False
            continue
        row_currency = "RUB"
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
        "cash_in": format(cash_in, "f"),
        "cash_out": format(cash_out, "f"),
        "currency": currency or "RUB",
    }, True


def _needs_cash_amount(row: RawImportRow) -> bool:
    return row.operation != "unpost" and not row.validation_errors


def _revenue_totals(rows: list[RawImportRow]) -> tuple[dict[str, Any] | None, bool]:
    revenue_net = Decimal("0.00")
    currency: str | None = None
    verifiable = True
    for row in rows:
        if row.operation == "unpost":
            continue
        data = row.normalized_payload
        if not data or row.validation_errors:
            if row.operation != "unpost":
                verifiable = False
            continue
        values = (data.get("values") or {})
        amount_raw = values.get("amount_ex_vat")
        if amount_raw is None or str(amount_raw).strip() == "":
            verifiable = False
            continue
        amount = _money(str(amount_raw))
        if amount is None:
            verifiable = False
            continue
        row_currency = "RUB"
        if currency is None:
            currency = row_currency
        elif currency != row_currency:
            return None, False
        revenue_net += amount
    if not verifiable:
        return None, False
    return {
        "record_count": _row_record_count(rows),
        "revenue_net": format(revenue_net, "f"),
        "currency": currency or "RUB",
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
            currency = item.get("currency", "RUB")
            cash_in += Decimal(item["cash_in"])
            cash_out += Decimal(item["cash_out"])
        merged["cash_in"] = format(cash_in, "f")
        merged["cash_out"] = format(cash_out, "f")
        merged["currency"] = currency or "RUB"
    elif dataset == "revenue":
        revenue_net = Decimal("0.00")
        currency = None
        for item in per_batch:
            if not item:
                continue
            currency = item.get("currency", "RUB")
            revenue_net += Decimal(item["revenue_net"])
        merged["revenue_net"] = format(revenue_net, "f")
        merged["currency"] = currency or "RUB"
    return merged, True


def validate_claim_fields(claim: dict[str, Any], dataset: str) -> None:
    from app.errors import AppError

    extra = set(claim) - MONEY_FIELDS - {"record_count", "currency"}
    if extra:
        raise AppError(
            422,
            "validation_error",
            f"Неподдерживаемые поля control_totals: {', '.join(sorted(extra))}",
        )
    currency = claim.get("currency")
    if currency is not None and currency not in SUPPORTED_CURRENCIES:
        raise AppError(422, "validation_error", "Неподдерживаемая валюта control_totals")
    if dataset in {"plan", "budget", "balances"}:
        money_in_claim = MONEY_FIELDS & set(claim)
        if money_in_claim:
            raise AppError(
                422,
                "validation_error",
                "Денежные control_totals недоступны для этого dataset",
            )


def compare_totals(claim: dict[str, Any], calculated: dict[str, Any], dataset: str) -> bool:
    if int(claim.get("record_count", -1)) != int(calculated.get("record_count", -2)):
        return False
    if dataset == "cash":
        return (
            claim.get("cash_in") == calculated.get("cash_in")
            and claim.get("cash_out") == calculated.get("cash_out")
            and claim.get("currency", "RUB") == calculated.get("currency", "RUB")
        )
    if dataset == "revenue":
        return (
            claim.get("revenue_net") == calculated.get("revenue_net")
            and claim.get("currency", "RUB") == calculated.get("currency", "RUB")
        )
    return True
