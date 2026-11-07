"""
P1b: версии профиля организации (без API). Подтверждение — owner/accountant.
Закрытые периоды: enforcement в P2b (см. assert_new_version_effective_from_allowed).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from app.domain.org_profile.resolution import (
    ResolvedOrganizationProfile,
    resolve_profile_for_period,
)
from app.domain.org_profile.validation import ProfileSnapshot, validate_profile_snapshot
from app.errors import AppError
from app.models.identity import Company, CompanyAccess, Membership
from app.models.org_profile import OrganizationProfileVersion
from app.security.access import ACCOUNTANT, OWNER, effective_role
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

PROFILE_CONFIRM_ROLES = frozenset({OWNER, ACCOUNTANT})


def snapshot_from_row(row: OrganizationProfileVersion) -> ProfileSnapshot:
    channels = row.money_channels if isinstance(row.money_channels, list) else ["unspecified"]
    return ProfileSnapshot(
        org_form=row.org_form,
        tax_system=row.tax_system,
        usn_tax_object=row.usn_tax_object,
        vat_status=row.vat_status,
        vat_regime_detail=row.vat_regime_detail,
        vat_default_rate=row.vat_default_rate,
        prices_include_vat=row.prices_include_vat,
        vat_exemption_article_145=row.vat_exemption_article_145,
        is_new_organization=row.is_new_organization,
        revenue_recognition_method=row.revenue_recognition_method,
        accounting_source=row.accounting_source,
        industry_sphere=row.industry_sphere,
        money_channels=channels,
        prior_year_revenue_band=row.prior_year_revenue_band,
        month_close_policy=row.month_close_policy,
    )


def assert_first_day_of_month(effective_from: date) -> None:
    if effective_from.day != 1:
        raise AppError(
            400,
            "invalid_effective_from",
            "effective_from должно быть первым числом месяца",
        )


def assert_new_version_effective_from_allowed(
    session: Session,
    *,
    company_id: UUID,
    effective_from: date,
) -> None:
    """Закрытые периоды: в репозитории пока нет — закрепим в P2b."""
    _ = (session, company_id, effective_from)


def load_company_in_tenant(
    session: Session, *, tenant_id: UUID, company_id: UUID
) -> Company:
    company = session.scalar(
        select(Company).where(Company.id == company_id, Company.tenant_id == tenant_id)
    )
    if company is None:
        raise AppError(404, "not_found", "Фирма не найдена")
    return company


def list_versions_for_company(
    session: Session, *, tenant_id: UUID, company_id: UUID
) -> list[OrganizationProfileVersion]:
    load_company_in_tenant(session, tenant_id=tenant_id, company_id=company_id)
    return list(
        session.scalars(
            select(OrganizationProfileVersion)
            .where(
                OrganizationProfileVersion.tenant_id == tenant_id,
                OrganizationProfileVersion.company_id == company_id,
            )
            .order_by(OrganizationProfileVersion.effective_from.asc())
        ).all()
    )


def create_organization_profile_version(
    session: Session,
    *,
    tenant_id: UUID,
    company_id: UUID,
    created_by: UUID,
    effective_from: date,
    snapshot: ProfileSnapshot,
    change_reason: str,
    at: datetime,
) -> OrganizationProfileVersion:
    assert_first_day_of_month(effective_from)
    assert_new_version_effective_from_allowed(
        session, company_id=company_id, effective_from=effective_from
    )
    company = load_company_in_tenant(session, tenant_id=tenant_id, company_id=company_id)
    result = validate_profile_snapshot(snapshot, company_inn=company.inn)
    if not result.is_valid:
        raise AppError(
            400,
            "profile_validation_failed",
            "Профиль содержит ошибки",
            details={"field_errors": result.field_errors},
        )

    row = OrganizationProfileVersion(
        tenant_id=tenant_id,
        company_id=company_id,
        effective_from=effective_from,
        org_form=snapshot.org_form,
        tax_system=snapshot.tax_system,
        usn_tax_object=snapshot.usn_tax_object,
        vat_status=snapshot.vat_status,
        vat_regime_detail=snapshot.vat_regime_detail,
        vat_default_rate=snapshot.vat_default_rate,
        prices_include_vat=snapshot.prices_include_vat,
        vat_exemption_article_145=snapshot.vat_exemption_article_145,
        is_new_organization=snapshot.is_new_organization,
        revenue_recognition_method=snapshot.revenue_recognition_method,
        accounting_source=snapshot.accounting_source,
        industry_sphere=snapshot.industry_sphere,
        money_channels=snapshot.money_channels or ["unspecified"],
        prior_year_revenue_band=snapshot.prior_year_revenue_band,
        month_close_policy=snapshot.month_close_policy,
        created_at=at,
        created_by=created_by,
        change_reason=change_reason,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as err:
        raise AppError(
            409,
            "profile_version_conflict",
            "Версия с такой датой уже существует",
        ) from err
    return row


def get_profile_for_period(
    session: Session,
    *,
    tenant_id: UUID,
    company_id: UUID,
    period_month: date,
) -> ResolvedOrganizationProfile | None:
    assert_first_day_of_month(period_month)
    versions = list_versions_for_company(session, tenant_id=tenant_id, company_id=company_id)
    tuples = [
        (
            str(v.id),
            v.effective_from,
            snapshot_from_row(v),
            v.confirmed_at is not None,
        )
        for v in versions
    ]
    return resolve_profile_for_period(versions=tuples, period_month=period_month)


def _effective_confirm_role(membership: Membership, access: CompanyAccess | None) -> str:
    role = effective_role(membership, access)
    if role not in PROFILE_CONFIRM_ROLES:
        raise AppError(403, "forbidden", "Подтверждать профиль могут owner и accountant")
    return role


def confirm_organization_profile_version(
    session: Session,
    *,
    tenant_id: UUID,
    company_id: UUID,
    version_id: UUID,
    membership: Membership,
    access: CompanyAccess | None,
    at: datetime,
) -> tuple[OrganizationProfileVersion, dict]:
    role = _effective_confirm_role(membership, access)
    load_company_in_tenant(session, tenant_id=tenant_id, company_id=company_id)

    versions = list_versions_for_company(session, tenant_id=tenant_id, company_id=company_id)
    if not versions:
        raise AppError(404, "not_found", "Версия профиля не найдена")
    latest = versions[-1]
    if latest.id != version_id:
        raise AppError(400, "not_latest_version", "Подтвердить можно только последнюю версию")

    row = session.scalar(
        select(OrganizationProfileVersion).where(
            OrganizationProfileVersion.id == version_id,
            OrganizationProfileVersion.tenant_id == tenant_id,
            OrganizationProfileVersion.company_id == company_id,
        )
    )
    if row is None:
        raise AppError(404, "not_found", "Версия профиля не найдена")
    if row.confirmed_at is not None:
        raise AppError(409, "already_confirmed", "Версия уже подтверждена")

    row.confirmed_at = at
    row.confirmed_by = membership.user_id
    row.confirmed_role = role
    session.flush()

    audit_event = {
        "action": "organization_profile_confirmed",
        "entity_type": "organization_profile_version",
        "entity_id": str(version_id),
        "tenant_id": str(tenant_id),
        "company_id": str(company_id),
        "user_id": str(membership.user_id),
        "confirmed_role": role,
        "effective_from": row.effective_from.isoformat(),
    }
    return row, audit_event


def assert_profile_fields_immutable(
    row: OrganizationProfileVersion,
    *,
    attempted_field: str,
) -> None:
    """Единственное изменение версии — подтверждение (вызов из тестов/будущего API)."""
    if attempted_field.startswith("confirmed_"):
        return
    raise AppError(409, "immutable_profile_version", "Поля версии профиля неизменяемы")
