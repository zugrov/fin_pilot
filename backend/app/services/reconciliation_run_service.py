"""FA-R03.3-min: append-only прогон сверки (без публичного product API)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from app.config import Settings
from app.errors import AppError
from app.models.identity import AuditLog, Membership, User
from app.models.provenance import ReconciliationRun
from app.security.access import CompanyAccess, can_write_finance
from app.security.context import set_context
from sqlalchemy import select, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_FORBIDDEN_JSON_KEYS = frozenset(
    {"purpose", "counterparty", "payer", "payee", "counterparty_name", "description"}
)

RUN_KIND_BANK_CARD_51 = "bank_card_51"
ENGINE_VERSION = "fa-r03.2-bank-card51/1"
QUALITY_FLAG_BANK_CARD51_DISCREPANCY = "bank_card51_discrepancy"
_PERSIST_STATUSES = frozenset({"passed", "completed_with_warnings"})


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


def bank_card51_persist_status(
    *,
    aligned: bool,
    chain_error_count: int,
    not_found_bank: int,
    not_found_card: int,
    needs_confirmation_groups: int,
    ambiguous_stage1: int,
) -> str:
    """Расхождение bank↔card51 — флаг качества, без блокировки (ADR-004 Q5)."""
    has_discrepancy = (
        not aligned
        or chain_error_count > 0
        or not_found_bank > 0
        or not_found_card > 0
        or needs_confirmation_groups > 0
        or ambiguous_stage1 > 0
    )
    if has_discrepancy:
        return "completed_with_warnings"
    return "passed"


def _latest_bank_card51_run_id(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    period_year: int,
    period_month: int,
) -> uuid.UUID | None:
    return session.scalar(
        select(ReconciliationRun.id)
        .where(
            ReconciliationRun.tenant_id == tenant_id,
            ReconciliationRun.company_id == company_id,
            ReconciliationRun.run_kind == RUN_KIND_BANK_CARD_51,
            ReconciliationRun.period_year == period_year,
            ReconciliationRun.period_month == period_month,
        )
        .order_by(
            ReconciliationRun.created_at.desc(),
            ReconciliationRun.id.desc(),
        )
        .limit(1)
    )


def _bank_card51_metrics(
    *,
    status: str,
    chain_error_count: int,
    matching: dict[str, Any],
    control_totals: dict[str, Any],
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "status": status,
        "matched_pair": int(matching.get("matched_pair", 0)),
        "group_matched_equivalent": int(matching.get("group_matched_equivalent", 0)),
        "not_found_bank": int(matching.get("not_found_bank", 0)),
        "not_found_card": int(matching.get("not_found_card", 0)),
        "needs_confirmation_groups": int(matching.get("needs_confirmation_groups", 0)),
        "chain_errors": chain_error_count,
        "control_totals": control_totals,
    }
    if status == "completed_with_warnings":
        metrics["quality_flag"] = QUALITY_FLAG_BANK_CARD51_DISCREPANCY
    return metrics


def record_bank_card51_run(
    session: Session,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    user: User,
    membership: Membership,
    access: CompanyAccess | None,
    period_year: int,
    period_month: int,
    aligned: bool,
    chain_error_count: int,
    matching: dict[str, Any],
    group_refs: list[dict[str, Any]],
    control_totals: dict[str, Any],
    input_fingerprints: list[dict[str, Any]],
    input_hashes: dict[str, Any],
    at: datetime,
) -> ReconciliationRun | None:
    """Append-only прогон после расчёта. Флаг выключен — запись не начинается."""
    if not settings.reconciliation_run_persist_enabled:
        return None
    assert_can_persist_run(membership, access, user)
    status = bank_card51_persist_status(
        aligned=aligned,
        chain_error_count=chain_error_count,
        not_found_bank=int(matching.get("not_found_bank", 0)),
        not_found_card=int(matching.get("not_found_card", 0)),
        needs_confirmation_groups=int(matching.get("needs_confirmation_groups", 0)),
        ambiguous_stage1=int(matching.get("stage1_ambiguous", 0)),
    )
    if status not in _PERSIST_STATUSES:
        return None
    metrics = _bank_card51_metrics(
        status=status,
        chain_error_count=chain_error_count,
        matching=matching,
        control_totals=control_totals,
    )
    try:
        set_context(session, tenant_id=tenant_id, user_id=user.id)
        # Сбой INSERT откатывает только savepoint: отчёт сверки уже посчитан.
        with session.begin_nested():
            previous_id = _latest_bank_card51_run_id(
                session,
                tenant_id=tenant_id,
                company_id=company_id,
                period_year=period_year,
                period_month=period_month,
            )
            row = persist_reconciliation_run(
                session,
                tenant_id=tenant_id,
                company_id=company_id,
                user=user,
                run_kind=RUN_KIND_BANK_CARD_51,
                period_year=period_year,
                period_month=period_month,
                input_fingerprints=input_fingerprints,
                input_hashes=input_hashes,
                metrics=metrics,
                group_refs=group_refs,
                engine_version=ENGINE_VERSION,
                at=at,
                supersedes_run_id=previous_id,
            )
            session.add(
                AuditLog(
                    tenant_id=tenant_id,
                    user_id=user.id,
                    action="reconciliation_run_recorded",
                    entity_type="reconciliation_run",
                    entity_id=row.id,
                    before_redacted=None,
                    after_redacted={
                        "run_kind": RUN_KIND_BANK_CARD_51,
                        "status": status,
                    },
                    request_id=None,
                    created_at=at,
                )
            )
        return row
    except AppError:
        raise
    except Exception as exc:
        logger.error(
            "reconciliation_run_persist_failed company_id=%s period=%s-%s error=%s",
            company_id,
            period_year,
            period_month,
            type(exc).__name__,
        )
        return None


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
