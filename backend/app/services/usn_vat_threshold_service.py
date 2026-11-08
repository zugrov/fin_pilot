"""Сбор данных для блока vat_threshold на дашборде."""

from __future__ import annotations

from datetime import date

from app.domain.org_profile.revenue_vat_overlay import month_start
from app.domain.usn_vat_threshold import (
    THRESHOLD_NORM_STATUSES,
    assess_usn_vat_threshold,
    vat_threshold_to_payload,
)
from app.models.imports import SourceConnection
from app.models.revenue import RevenueEntry
from app.services.org_profile_service import get_profile_for_period
from app.services.revenue_coverage import sources_coverage_through
from app.services.tax_norms_service import get_version_for_date
from sqlalchemy import select
from sqlalchemy.orm import Session

_ELIGIBLE_VAT = frozenset({"not_applicable", "exemption"})


def vat_threshold_for_dashboard(
    session: Session,
    company,
    *,
    as_of: date,
) -> dict | None:
    period_month = month_start(as_of)
    resolved = get_profile_for_period(
        session,
        tenant_id=company.tenant_id,
        company_id=company.id,
        period_month=period_month,
    )
    if resolved is None or not resolved.is_confirmed:
        return None
    snap = resolved.snapshot
    if snap.tax_system != "usn" or snap.vat_status not in _ELIGIBLE_VAT:
        return None

    norm = get_version_for_date(session, as_of)
    if norm is None or norm.status not in THRESHOLD_NORM_STATUSES:
        return None
    threshold = norm.usn_vat_exemption_threshold_rub
    if threshold is None:
        return None

    year_start = date(as_of.year, 1, 1)
    entries = list(
        session.scalars(
            select(RevenueEntry).where(
                RevenueEntry.tenant_id == company.tenant_id,
                RevenueEntry.company_id == company.id,
                RevenueEntry.status == "posted",
                RevenueEntry.recognition_date >= year_start,
                RevenueEntry.recognition_date <= as_of,
            )
        ).all()
    )
    sources = list(
        session.scalars(
            select(SourceConnection).where(
                SourceConnection.tenant_id == company.tenant_id,
                SourceConnection.company_id == company.id,
                SourceConnection.dataset == "revenue",
                SourceConnection.status == "active",
            )
        ).all()
    )
    covered, _ = sources_coverage_through(sources, as_of)
    partial = not covered
    rows = tuple(
        (item.recognition_date, item.entry_type, item.amount_inc_vat) for item in entries
    )
    view = assess_usn_vat_threshold(rows, as_of=as_of, threshold=threshold, partial=partial)
    return vat_threshold_to_payload(view)
