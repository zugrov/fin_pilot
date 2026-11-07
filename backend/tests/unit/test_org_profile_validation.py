from app.domain.org_profile.confirm import validate_confirm_readiness
from app.domain.org_profile.validation import ProfileSnapshot, validate_profile_snapshot


def test_draft_allows_usn_without_tax_object() -> None:
    snap = ProfileSnapshot(tax_system="usn", usn_tax_object="unspecified")
    result = validate_profile_snapshot(snap)
    assert "required_for_usn" not in result.field_errors.get("usn_tax_object", [])
    assert result.is_valid


def test_confirm_readiness_requires_usn_tax_object() -> None:
    snap = ProfileSnapshot(tax_system="usn", usn_tax_object="unspecified")
    result = validate_confirm_readiness(snap)
    assert "usn_tax_object" in result.field_errors.get("_confirm_minimum", [])


def test_vat_deductions_only_for_payer() -> None:
    snap = ProfileSnapshot(
        vat_status="exemption",
        vat_regime_detail="with_deductions",
    )
    result = validate_profile_snapshot(snap)
    assert "with_deductions_requires_vat_payer" in result.field_errors["vat_regime_detail"]


def test_vat_default_rate_only_for_payer() -> None:
    snap = ProfileSnapshot(vat_status="not_applicable", vat_default_rate="22")
    result = validate_profile_snapshot(snap)
    assert "only_for_vat_payer" in result.field_errors["vat_default_rate"]


def test_article_145_exemption_only() -> None:
    snap = ProfileSnapshot(vat_status="vat_payer", vat_exemption_article_145=True)
    result = validate_profile_snapshot(snap)
    assert "only_for_exemption" in result.field_errors["vat_exemption_article_145"]


def test_new_org_clears_prior_band() -> None:
    snap = ProfileSnapshot(
        is_new_organization=True, prior_year_revenue_band="under_exemption_threshold"
    )
    result = validate_profile_snapshot(snap)
    assert "must_be_empty_for_new_org" in result.field_errors["prior_year_revenue_band"]


def test_unsupported_tax_system_not_field_error() -> None:
    snap = ProfileSnapshot(tax_system="ausn", org_form="ooo", accounting_source="onec")
    result = validate_profile_snapshot(snap)
    assert result.is_valid
    assert result.support is not None
    assert result.support.level == "unsupported"
    assert result.support.code == "tax_system_not_supported"


def test_inn_validation_on_company() -> None:
    snap = ProfileSnapshot()
    result = validate_profile_snapshot(snap, company_inn="7707083890")
    assert "inn_checksum_mismatch" in result.field_errors.get("inn", [])


def test_special_rates_requires_usn() -> None:
    snap = ProfileSnapshot(tax_system="osno", vat_status="special_rates_5_7")
    result = validate_profile_snapshot(snap)
    assert "special_rates_requires_usn" in result.field_errors.get("vat_status", [])


def test_ooo_psn_incompatible() -> None:
    snap = ProfileSnapshot(org_form="ooo", tax_system="psn")
    result = validate_profile_snapshot(snap)
    assert "ooo_incompatible_with_ip_regime" in result.field_errors.get("tax_system", [])


def test_invalid_enum_org_form() -> None:
    snap = ProfileSnapshot(org_form="llc")
    result = validate_profile_snapshot(snap)
    assert "invalid_value" in result.field_errors.get("org_form", [])
