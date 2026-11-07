"""P2a: чтение профиля организации (без записи)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from app.api.deps import DbSession, current_session
from app.clock import now
from app.domain.org_profile.validation import ProfileSnapshot
from app.errors import AppError
from app.security.access import find_company_across_memberships
from app.services.org_profile_service import (
    get_profile_for_period,
    list_versions_for_company,
)
from fastapi import APIRouter, Request

router = APIRouter(tags=["organization-profile"])


def _default_period_month(at: datetime, timezone: str) -> date:
    local = at.astimezone(ZoneInfo(timezone or "Europe/Moscow"))
    return date(local.year, local.month, 1)


def _parse_period(request: Request, company_timezone: str, at: datetime) -> date:
    raw = request.query_params.get("period")
    if not raw:
        return _default_period_month(at, company_timezone)
    try:
        parsed = date.fromisoformat(raw)
    except ValueError as exc:
        raise AppError(400, "validation_error", "Некорректный период period") from exc
    if parsed.day != 1:
        raise AppError(
            400,
            "validation_error",
            "period должно быть первым числом месяца (YYYY-MM-01)",
        )
    return parsed


def _snapshot_payload(snapshot: ProfileSnapshot) -> dict:
    channels = snapshot.money_channels if isinstance(snapshot.money_channels, list) else []
    return {
        "org_form": snapshot.org_form,
        "tax_system": snapshot.tax_system,
        "usn_tax_object": snapshot.usn_tax_object,
        "vat_status": snapshot.vat_status,
        "vat_regime_detail": snapshot.vat_regime_detail,
        "vat_default_rate": snapshot.vat_default_rate,
        "prices_include_vat": snapshot.prices_include_vat,
        "vat_exemption_article_145": snapshot.vat_exemption_article_145,
        "is_new_organization": snapshot.is_new_organization,
        "revenue_recognition_method": snapshot.revenue_recognition_method,
        "accounting_source": snapshot.accounting_source,
        "industry_sphere": snapshot.industry_sphere,
        "money_channels": channels,
        "prior_year_revenue_band": snapshot.prior_year_revenue_band,
        "month_close_policy": snapshot.month_close_policy,
    }


def _ts_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _company_read(request: Request, session: DbSession, company_id: UUID):
    """Как GET /api/v1/companies/{company_id}: сессия и видимость фирмы, без billing."""
    _row, user = current_session(request, session)
    membership, company = find_company_across_memberships(session, user.id, company_id)
    _ = (membership, user)
    return company, now()


@router.get("/companies/{company_id}/organization-profile")
def get_organization_profile_for_period(
    company_id: UUID,
    request: Request,
    session: DbSession,
) -> dict:
    company, at = _company_read(request, session, company_id)
    period_month = _parse_period(request, company.timezone, at)
    resolved = get_profile_for_period(
        session,
        tenant_id=company.tenant_id,
        company_id=company.id,
        period_month=period_month,
    )
    if resolved is None:
        raise AppError(404, "not_found", "Профиль не найден")
    support = resolved.support
    return {
        "company_id": str(company.id),
        "period": period_month.isoformat(),
        "version_id": resolved.version_id,
        "effective_from": resolved.effective_from.isoformat(),
        "is_confirmed": resolved.is_confirmed,
        "confirmed_at": _ts_iso(resolved.confirmed_at),
        "confirmed_role": resolved.confirmed_role,
        "profile_unconfirmed": not resolved.is_confirmed,
        "support_level": support.level,
        "support_code": support.code,
        **_snapshot_payload(resolved.snapshot),
    }


@router.get("/companies/{company_id}/organization-profile/versions")
def list_organization_profile_versions(
    company_id: UUID,
    request: Request,
    session: DbSession,
) -> dict:
    company, _at = _company_read(request, session, company_id)
    versions = list_versions_for_company(
        session, tenant_id=company.tenant_id, company_id=company.id
    )
    items: list[dict] = []
    for row in versions:
        items.append(
            {
                "version_id": str(row.id),
                "effective_from": row.effective_from.isoformat(),
                "is_confirmed": row.confirmed_at is not None,
                "confirmed_at": _ts_iso(row.confirmed_at),
                "confirmed_role": row.confirmed_role,
                "change_reason": row.change_reason,
                "created_at": _ts_iso(row.created_at),
            }
        )
    return {"company_id": str(company.id), "versions": items}
