"""Чистая валидация снимка профиля (ADR-003 §2, §7)."""

from dataclasses import dataclass, field

from app.domain.org_profile.inn import validate_inn_checksum
from app.domain.org_profile.support_matrix import SupportAssessment, assess_product_support

VAT_PAYER = "vat_payer"
SPECIAL_RATES = "special_rates_5_7"
EXEMPTION = "exemption"
NOT_APPLICABLE = "not_applicable"

WITH_DEDUCTIONS = "with_deductions"
SPECIAL_WITHOUT = "special_without_deductions"

USN = "usn"


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


def validate_profile_snapshot(
    snapshot: ProfileSnapshot,
    *,
    company_inn: str | None = None,
) -> ProfileValidationResult:
    errors: dict[str, list[str]] = {}

    if snapshot.tax_system == USN:
        if snapshot.usn_tax_object in (None, "", "unspecified", "unknown"):
            errors.setdefault("usn_tax_object", []).append("required_for_usn")
    elif snapshot.usn_tax_object not in (None, "", "unspecified", "unknown"):
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
