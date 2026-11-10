"""FA-R03.3-min: append-only прогон сверки (без публичного product API)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.config import Settings
from app.errors import AppError
from app.models.identity import Membership, User
from app.models.provenance import ReconciliationRun
from app.security.access import CompanyAccess, can_write_finance
from sqlalchemy import text
from sqlalchemy.orm import Session

_FORBIDDEN_JSON_KEYS = frozenset(
    {"purpose", "counterparty", "payer", "payee", "counterparty_name", "description"}
)


def _scrub_json(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if key in _FORBIDDEN_JSON_KEYS:
                continue
            cleaned[key] = _scrub_json(item)
        return cleaned
    if isinstance(value, list):
        return [_scrub_json(item) for item in value]
    return value


def assert_can_persist_run(
    membership: Membership, access: CompanyAccess | None, user: User
) -> None:
    if not can_write_finance(membership, access):
        raise AppError(403, "forbidden", "Недостаточно прав для записи прогона сверки")
    if user.email_verified_at is None:
        raise AppError(403, "email_unverified", "Подтвердите email для записи прогона сверки")


def persist_reconciliation_run(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    user: User,
    run_kind: str,
    period_year: int,
    period_month: int,
    input_fingerprints: list[dict[str, Any]],
    input_hashes: dict[str, Any],
    metrics: dict[str, Any],
    group_refs: list[dict[str, Any]],
    engine_version: str,
    at: datetime,
    supersedes_run_id: uuid.UUID | None = None,
) -> ReconciliationRun:
    if period_month < 1 or period_month > 12:
        raise AppError(422, "validation_error", "Некорректный месяц периода")
    row = ReconciliationRun(
        tenant_id=tenant_id,
        company_id=company_id,
        run_kind=run_kind,
        period_year=period_year,
        period_month=period_month,
        input_fingerprints=_scrub_json(input_fingerprints),
        input_hashes=_scrub_json(input_hashes),
        metrics=_scrub_json(metrics),
        group_refs=_scrub_json(group_refs),
        engine_version=engine_version,
        created_by_user_id=user.id,
        created_at=at,
        supersedes_run_id=supersedes_run_id,
    )
    session.add(row)
    session.flush()
    return row


def expire_reconciliation_runs(
    session: Session, settings: Settings, *, before: datetime, limit: int = 500
) -> int:
    months = settings.reconciliation_run_retention_months
    if months < 1:
        return 0
    result = session.execute(
        text("SELECT app_expire_reconciliation_runs(:before, :limit)"),
        {"before": before, "limit": limit},
    )
    return int(result.scalar_one())
