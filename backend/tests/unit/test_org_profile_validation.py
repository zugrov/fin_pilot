from app.domain.org_profile.validation import ProfileSnapshot, validate_profile_snapshot


def test_usn_requires_tax_object() -> None:
    snap = ProfileSnapshot(tax_system="usn", usn_tax_object="unspecified")
    result = validate_profile_snapshot(snap)
    assert "required_for_usn" in result.field_errors.get("usn_tax_object", [])


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
    snap = ProfileSnapshot(is_new_organization=True, prior_year_revenue_band="under_20m")
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
