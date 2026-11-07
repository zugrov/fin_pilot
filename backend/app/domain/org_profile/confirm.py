"""Готовность профиля к подтверждению (минимум полей)."""

from app.domain.org_profile.constants import MONEY_CHANNELS
from app.domain.org_profile.validation import (
    USN,
    VAT_PAYER,
    ProfileSnapshot,
    ProfileValidationResult,
    validate_profile_snapshot,
)

_PLACEHOLDER = frozenset({None, "", "unspecified", "unknown"})


def validate_confirm_readiness(
    snapshot: ProfileSnapshot,
    *,
    company_inn: str | None = None,
) -> ProfileValidationResult:
    result = validate_profile_snapshot(snapshot, company_inn=company_inn)
    missing: list[str] = []

    if snapshot.org_form in _PLACEHOLDER:
        missing.append("org_form")
    if snapshot.tax_system in _PLACEHOLDER:
        missing.append("tax_system")
    if snapshot.tax_system == USN and snapshot.usn_tax_object in _PLACEHOLDER:
        missing.append("usn_tax_object")
    if snapshot.vat_status in _PLACEHOLDER:
        missing.append("vat_status")
    if snapshot.vat_status == VAT_PAYER:
        if snapshot.vat_default_rate in _PLACEHOLDER or snapshot.vat_default_rate not in (
            "22",
            "10",
            "0",
        ):
            missing.append("vat_default_rate")
    if snapshot.accounting_source in _PLACEHOLDER:
        missing.append("accounting_source")
    if snapshot.revenue_recognition_method in _PLACEHOLDER:
        missing.append("revenue_recognition_method")
    if snapshot.month_close_policy in _PLACEHOLDER:
        missing.append("month_close_policy")

    channels = snapshot.money_channels or []
    usable = [ch for ch in channels if ch not in _PLACEHOLDER and ch != "unspecified"]
    if not usable:
        missing.append("money_channels")
    elif any(ch not in MONEY_CHANNELS for ch in channels):
        result.field_errors.setdefault("money_channels", []).append("invalid_value")

    if snapshot.is_new_organization is not True:
        if snapshot.prior_year_revenue_band in _PLACEHOLDER:
            missing.append("prior_year_revenue_band")

    if missing:
        result.field_errors.setdefault("_confirm_minimum", []).extend(missing)

    return result
