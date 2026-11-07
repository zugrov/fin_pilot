"""P2a/P2b: чтение и запись профиля организации."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from app.api.deps import DbSession, current_session, require_csrf
from app.clock import now
from app.domain.org_profile.validation import ProfileSnapshot
from app.errors import AppError
from app.models.identity import AuditLog, IdempotencyRecord, User
from app.models.org_profile import OrganizationProfileVersion
from app.security.access import (
    ACCOUNTANT,
    OWNER,
    access_row,
    effective_role,
    find_company_across_memberships,
)
from app.security.tokens import canonical_hash
from app.services.org_profile_service import (
    confirm_organization_profile_version,
    create_organization_profile_version,
    get_profile_for_period,
    list_versions_for_company,
    snapshot_from_row,
    update_draft_profile_version,
)
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

router = APIRouter(tags=["organization-profile"])

PROFILE_WRITE_ROLES = frozenset({OWNER, ACCOUNTANT})
_IDEM_SCOPE_VERSION = "org_profile_version"
_IDEM_SCOPE_CONFIRM = "org_profile_confirm"


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


class ProfileFieldsIn(BaseModel):
    org_form: str = "unspecified"
    tax_system: str = "unspecified"
    usn_tax_object: str = "unspecified"
    vat_status: str = "unknown"
    vat_regime_detail: str | None = None
    vat_default_rate: str | None = None
    prices_include_vat: str = "unknown"
    vat_exemption_article_145: bool | None = None
    is_new_organization: bool | None = None
    revenue_recognition_method: str = "unknown"
    accounting_source: str = "unspecified"
    industry_sphere: str = "unspecified"
    money_channels: list[str] | None = None
    prior_year_revenue_band: str = "unknown"
    month_close_policy: str = "unknown"


class DraftProfilePatchIn(ProfileFieldsIn):
    change_reason: str = Field(min_length=1, max_length=2000)


class ProfileVersionCreateIn(ProfileFieldsIn):
    effective_from: date
    change_reason: str = Field(min_length=1, max_length=2000)


def _snapshot_from_in(payload: ProfileFieldsIn) -> ProfileSnapshot:
    return ProfileSnapshot(
        org_form=payload.org_form,
        tax_system=payload.tax_system,
        usn_tax_object=payload.usn_tax_object,
        vat_status=payload.vat_status,
        vat_regime_detail=payload.vat_regime_detail,
        vat_default_rate=payload.vat_default_rate,
        prices_include_vat=payload.prices_include_vat,
        vat_exemption_article_145=payload.vat_exemption_article_145,
        is_new_organization=payload.is_new_organization,
        revenue_recognition_method=payload.revenue_recognition_method,
        accounting_source=payload.accounting_source,
        industry_sphere=payload.industry_sphere,
        money_channels=payload.money_channels,
        prior_year_revenue_band=payload.prior_year_revenue_band,
        month_close_policy=payload.month_close_policy,
    )


def _enum_field_names() -> tuple[str, ...]:
    return (
        "org_form",
        "tax_system",
        "usn_tax_object",
        "vat_status",
        "vat_regime_detail",
        "vat_default_rate",
        "prices_include_vat",
        "is_new_organization",
        "revenue_recognition_method",
        "accounting_source",
        "industry_sphere",
        "money_channels",
        "prior_year_revenue_band",
        "month_close_policy",
        "vat_exemption_article_145",
    )


def _snapshot_audit_values(snapshot: ProfileSnapshot) -> dict:
    raw = _snapshot_payload(snapshot)
    if snapshot.vat_exemption_article_145 is not None:
        raw["vat_exemption_article_145"] = snapshot.vat_exemption_article_145
    return raw


def _diff_snapshots(before: ProfileSnapshot, after: ProfileSnapshot) -> dict:
    prev = _snapshot_audit_values(before)
    nxt = _snapshot_audit_values(after)
    changed: dict = {}
    for key in _enum_field_names():
        if prev.get(key) != nxt.get(key):
            changed[key] = nxt.get(key)
    return changed


def _version_write_payload(row: OrganizationProfileVersion) -> dict:
    snap = snapshot_from_row(row)
    return {
        "version_id": str(row.id),
        "company_id": str(row.company_id),
        "effective_from": row.effective_from.isoformat(),
        "is_confirmed": row.confirmed_at is not None,
        "confirmed_at": _ts_iso(row.confirmed_at),
        "confirmed_role": row.confirmed_role,
        "change_reason": row.change_reason,
        "created_at": _ts_iso(row.created_at),
        **_snapshot_payload(snap),
    }


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _write_audit(
    session,
    *,
    user: User,
    tenant_id: UUID,
    action: str,
    entity_id: UUID,
    before: dict | None,
    after: dict | None,
    at: datetime,
    request: Request,
) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user.id,
            action=action,
            entity_type="organization_profile_version",
            entity_id=entity_id,
            before_redacted=before,
            after_redacted=after,
            request_id=_request_id(request),
            created_at=at,
        )
    )


def _idempotency_key(request: Request) -> str:
    key = request.headers.get("idempotency-key")
    if not key:
        raise AppError(400, "validation_error", "Нужен заголовок Idempotency-Key")
    return key


def _idempotency_hash(body: dict) -> str:
    return canonical_hash(json.dumps(body, sort_keys=True, separators=(",", ":")))


def _idempotent_begin(
    session,
    user: User,
    *,
    tenant_id: UUID,
    scope: str,
    key: str,
    request_hash: str,
) -> dict | None:
    row = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if row is None:
        return None
    if row.request_hash != request_hash:
        raise AppError(409, "idempotency_conflict", "Ключ уже использован с другим запросом")
    return row.response_body if row.response_body else None


def _idempotent_store(
    session,
    user: User,
    *,
    tenant_id: UUID,
    scope: str,
    key: str,
    request_hash: str,
    body: dict,
    at: datetime,
) -> None:
    record = IdempotencyRecord(
        tenant_id=tenant_id,
        user_id=user.id,
        scope=scope,
        idempotency_key=key,
        request_hash=request_hash,
        status_code=200,
        response_body=body,
        payment_attempt_id=None,
        created_at=at,
    )
    try:
        with session.begin_nested():
            session.add(record)
            session.flush()
    except IntegrityError:
        row = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.user_id == user.id,
                IdempotencyRecord.scope == scope,
                IdempotencyRecord.idempotency_key == key,
            )
        )
        if row is not None and row.request_hash == request_hash:
            return
        raise AppError(
            409,
            "idempotency_conflict",
            "Ключ уже использован с другим запросом",
        ) from None


def _assert_verified_email(user: User) -> None:
    if user.email_verified_at is None:
        raise AppError(403, "email_not_verified", "Подтвердите почту")


def _company_session(
    request: Request, session: DbSession, company_id: UUID, *, mutate: bool
) -> tuple:
    row, user = current_session(request, session)
    if mutate:
        require_csrf(request, row)
        _assert_verified_email(user)
    membership, company = find_company_across_memberships(session, user.id, company_id)
    access = access_row(session, membership, company.id)
    return row, user, membership, company, access


def _assert_profile_writer(membership, access) -> str:
    role = effective_role(membership, access)
    if role not in PROFILE_WRITE_ROLES:
        raise AppError(403, "forbidden", "Редактировать профиль могут owner и accountant")
    return role


def _company_read(request: Request, session: DbSession, company_id: UUID):
    _row, user, _m, company, _a = _company_session(request, session, company_id, mutate=False)
    _ = (_row, user, _a)
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


@router.patch("/companies/{company_id}/organization-profile/draft")
def patch_organization_profile_draft(
    company_id: UUID,
    payload: DraftProfilePatchIn,
    request: Request,
    session: DbSession,
) -> dict:
    _row, user, membership, company, access = _company_session(
        request, session, company_id, mutate=True
    )
    _ = (_row, access)
    _assert_profile_writer(membership, access)
    versions = list_versions_for_company(
        session, tenant_id=company.tenant_id, company_id=company.id
    )
    if not versions:
        raise AppError(404, "not_found", "Версия профиля не найдена")
    latest = versions[-1]
    before = snapshot_from_row(latest)
    at = now()
    row = update_draft_profile_version(
        session,
        tenant_id=company.tenant_id,
        company_id=company.id,
        version_id=latest.id,
        snapshot=_snapshot_from_in(payload),
        change_reason=payload.change_reason,
    )
    after = snapshot_from_row(row)
    changed = _diff_snapshots(before, after)
    if changed:
        _write_audit(
            session,
            user=user,
            tenant_id=company.tenant_id,
            action="organization_profile_draft_updated",
            entity_id=row.id,
            before={k: _snapshot_audit_values(before)[k] for k in changed},
            after={**changed, "change_reason": payload.change_reason},
            at=at,
            request=request,
        )
    return _version_write_payload(row)


@router.post("/companies/{company_id}/organization-profile/versions")
def post_organization_profile_version(
    company_id: UUID,
    payload: ProfileVersionCreateIn,
    request: Request,
    session: DbSession,
) -> dict:
    _row, user, membership, company, access = _company_session(
        request, session, company_id, mutate=True
    )
    _ = (_row, access)
    _assert_profile_writer(membership, access)
    key = _idempotency_key(request)
    body_for_hash = payload.model_dump(mode="json")
    body_for_hash["company_id"] = str(company_id)
    req_hash = _idempotency_hash(body_for_hash)
    cached = _idempotent_begin(
        session,
        user,
        tenant_id=company.tenant_id,
        scope=_IDEM_SCOPE_VERSION,
        key=key,
        request_hash=req_hash,
    )
    if cached is not None:
        return cached
    at = now()
    row = create_organization_profile_version(
        session,
        tenant_id=company.tenant_id,
        company_id=company.id,
        created_by=user.id,
        effective_from=payload.effective_from,
        snapshot=_snapshot_from_in(payload),
        change_reason=payload.change_reason,
        at=at,
    )
    result = _version_write_payload(row)
    _write_audit(
        session,
        user=user,
        tenant_id=company.tenant_id,
        action="organization_profile_version_created",
        entity_id=row.id,
        before=None,
        after={
            "effective_from": row.effective_from.isoformat(),
            "change_reason": payload.change_reason,
            **_snapshot_payload(_snapshot_from_in(payload)),
        },
        at=at,
        request=request,
    )
    _idempotent_store(
        session,
        user,
        tenant_id=company.tenant_id,
        scope=_IDEM_SCOPE_VERSION,
        key=key,
        request_hash=req_hash,
        body=result,
        at=at,
    )
    return result


@router.post("/companies/{company_id}/organization-profile/versions/{version_id}/confirm")
def post_confirm_organization_profile_version(
    company_id: UUID,
    version_id: UUID,
    request: Request,
    session: DbSession,
) -> dict:
    _row, user, membership, company, access = _company_session(
        request, session, company_id, mutate=True
    )
    _ = _row
    _assert_profile_writer(membership, access)
    key = _idempotency_key(request)
    body_for_hash = {"company_id": str(company_id), "version_id": str(version_id)}
    req_hash = _idempotency_hash(body_for_hash)
    cached = _idempotent_begin(
        session,
        user,
        tenant_id=company.tenant_id,
        scope=_IDEM_SCOPE_CONFIRM,
        key=key,
        request_hash=req_hash,
    )
    if cached is not None:
        return cached
    at = now()
    row, _event = confirm_organization_profile_version(
        session,
        tenant_id=company.tenant_id,
        company_id=company.id,
        version_id=version_id,
        membership=membership,
        access=access,
        at=at,
    )
    role = effective_role(membership, access)
    result = _version_write_payload(row)
    _write_audit(
        session,
        user=user,
        tenant_id=company.tenant_id,
        action="organization_profile_confirmed",
        entity_id=row.id,
        before=None,
        after={
            "version_id": str(row.id),
            "effective_from": row.effective_from.isoformat(),
            "confirmed_role": role,
        },
        at=at,
        request=request,
    )
    _idempotent_store(
        session,
        user,
        tenant_id=company.tenant_id,
        scope=_IDEM_SCOPE_CONFIRM,
        key=key,
        request_hash=req_hash,
        body=result,
        at=at,
    )
    return result
