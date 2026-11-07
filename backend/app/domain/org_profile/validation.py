"""Чистая валидация снимка профиля (ADR-003 §2, §7)."""

from dataclasses import dataclass, field

from app.domain.org_profile.constants import (
    ACCOUNTING_SOURCES,
    INDUSTRY_SPHERES,
    IP_ONLY_TAX_SYSTEMS,
    MONEY_CHANNELS,
    MONTH_CLOSE_POLICIES,
    ORG_FORMS,
    PRICES_INCLUDE_VAT,
    PRIOR_YEAR_REVENUE_BANDS,
    REVENUE_RECOGNITION_METHODS,
    TAX_SYSTEMS,
    USN_TAX_OBJECTS,
    VAT_DEFAULT_RATE_VALUES,
    VAT_REGIME_DETAIL_VALUES,
    VAT_STATUSES,
)
from app.domain.org_profile.inn import validate_inn_checksum
from app.domain.org_profile.support_matrix import SupportAssessment, assess_product_support

VAT_PAYER = "vat_payer"
SPECIAL_RATES = "special_rates_5_7"
EXEMPTION = "exemption"
NOT_APPLICABLE = "not_applicable"

WITH_DEDUCTIONS = "with_deductions"
SPECIAL_WITHOUT = "special_without_deductions"

USN = "usn"
OOO = "ooo"
IP = "ip"


@dataclass(slots=True)
class ProfileSnapshot:
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


@dataclass(slots=True)
class ProfileValidationResult:
    field_errors: dict[str, list[str]] = field(default_factory=dict)
    support: SupportAssessment | None = None

    @property
    def is_valid(self) -> bool:
        return not self.field_errors


def validate_profile_draft_snapshot(
    snapshot: ProfileSnapshot,
    *,
    company_inn: str | None = None,
) -> ProfileValidationResult:
    """Согласованность и перечни значений; без проверок полноты для подтверждения."""
    errors: dict[str, list[str]] = {}

    _validate_enums(snapshot, errors)
    _validate_form_tax_compatibility(snapshot, errors)

    if snapshot.tax_system != USN and snapshot.usn_tax_object not in (
        None,
        "",
        "unspecified",
        "unknown",
    ):
        errors.setdefault("usn_tax_object", []).append("only_for_usn")

    _validate_vat_block(snapshot, errors)
    _validate_new_org_band(snapshot, errors)

    if company_inn is not None:
        for code in validate_inn_checksum(company_inn):
            errors.setdefault("inn", []).append(code)

    support = assess_product_support(
        org_form=snapshot.org_form,
        tax_system=snapshot.tax_system,
        accounting_source=snapshot.accounting_source,
    )
    return ProfileValidationResult(field_errors=errors, support=support)


def validate_profile_snapshot(
    snapshot: ProfileSnapshot,
    *,
    company_inn: str | None = None,
) -> ProfileValidationResult:
    """Алиас черновой валидации (полнота — в validate_confirm_readiness)."""
    return validate_profile_draft_snapshot(snapshot, company_inn=company_inn)


def _validate_enums(snapshot: ProfileSnapshot, errors: dict[str, list[str]]) -> None:
    if snapshot.org_form not in ORG_FORMS:
        errors.setdefault("org_form", []).append("invalid_value")
    if snapshot.tax_system not in TAX_SYSTEMS:
        errors.setdefault("tax_system", []).append("invalid_value")
    if snapshot.usn_tax_object not in USN_TAX_OBJECTS:
        errors.setdefault("usn_tax_object", []).append("invalid_value")
    if snapshot.vat_status not in VAT_STATUSES:
        errors.setdefault("vat_status", []).append("invalid_value")
    if snapshot.vat_regime_detail is not None and snapshot.vat_regime_detail not in (
        VAT_REGIME_DETAIL_VALUES
    ):
        errors.setdefault("vat_regime_detail", []).append("invalid_value")
    if snapshot.vat_default_rate is not None and snapshot.vat_default_rate not in (
        VAT_DEFAULT_RATE_VALUES
    ):
        errors.setdefault("vat_default_rate", []).append("invalid_value")
    if snapshot.prices_include_vat not in PRICES_INCLUDE_VAT:
        errors.setdefault("prices_include_vat", []).append("invalid_value")
    if snapshot.revenue_recognition_method not in REVENUE_RECOGNITION_METHODS:
        errors.setdefault("revenue_recognition_method", []).append("invalid_value")
    if snapshot.accounting_source not in ACCOUNTING_SOURCES:
        errors.setdefault("accounting_source", []).append("invalid_value")
    if snapshot.industry_sphere not in INDUSTRY_SPHERES:
        errors.setdefault("industry_sphere", []).append("invalid_value")
    if snapshot.prior_year_revenue_band not in PRIOR_YEAR_REVENUE_BANDS:
        errors.setdefault("prior_year_revenue_band", []).append("invalid_value")
    if snapshot.month_close_policy not in MONTH_CLOSE_POLICIES:
        errors.setdefault("month_close_policy", []).append("invalid_value")
    channels = snapshot.money_channels or []
    for ch in channels:
        if ch not in MONEY_CHANNELS:
            errors.setdefault("money_channels", []).append("invalid_value")
            break


def _validate_form_tax_compatibility(
    snapshot: ProfileSnapshot, errors: dict[str, list[str]]
) -> None:
    ts = snapshot.tax_system
    form = snapshot.org_form
    vs = snapshot.vat_status

    if vs == SPECIAL_RATES and ts != USN:
        errors.setdefault("vat_status", []).append("special_rates_requires_usn")

    if ts in IP_ONLY_TAX_SYSTEMS and form != IP:
        errors.setdefault("tax_system", []).append("regime_requires_ip")

    if form == OOO and ts in IP_ONLY_TAX_SYSTEMS:
        errors.setdefault("tax_system", []).append("ooo_incompatible_with_ip_regime")


def _validate_vat_block(snapshot: ProfileSnapshot, errors: dict[str, list[str]]) -> None:
    detail = snapshot.vat_regime_detail
    rate = snapshot.vat_default_rate
    article_145 = snapshot.vat_exemption_article_145

    if detail == WITH_DEDUCTIONS:
        if snapshot.vat_status != VAT_PAYER:
            errors.setdefault("vat_regime_detail", []).append("with_deductions_requires_vat_payer")
    elif detail == SPECIAL_WITHOUT:
        if snapshot.vat_status != SPECIAL_RATES:
            errors.setdefault("vat_regime_detail", []).append(
                "special_without_requires_special_rates"
            )
    elif detail not in (None, "", "unspecified"):
        errors.setdefault("vat_regime_detail", []).append("invalid_value")

    if article_145 is True:
        if snapshot.vat_status != EXEMPTION:
            errors.setdefault("vat_exemption_article_145", []).append("only_for_exemption")
        if detail == WITH_DEDUCTIONS:
            errors.setdefault("vat_exemption_article_145", []).append(
                "incompatible_with_deductions"
            )

    if rate not in (None, "", "unspecified"):
        if snapshot.vat_status != VAT_PAYER:
            errors.setdefault("vat_default_rate", []).append("only_for_vat_payer")
        elif rate not in {"22", "10", "0"}:
            errors.setdefault("vat_default_rate", []).append("invalid_rate")


def _validate_new_org_band(snapshot: ProfileSnapshot, errors: dict[str, list[str]]) -> None:
    if snapshot.is_new_organization is True:
        if snapshot.prior_year_revenue_band not in (
            None,
            "",
            "unknown",
            "unspecified",
        ):
            errors.setdefault("prior_year_revenue_band", []).append("must_be_empty_for_new_org")
