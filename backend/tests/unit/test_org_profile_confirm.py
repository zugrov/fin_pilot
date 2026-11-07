from app.domain.org_profile.confirm import validate_confirm_readiness
from app.domain.org_profile.validation import ProfileSnapshot


def _complete_snapshot(**kwargs) -> ProfileSnapshot:
    base = dict(
        org_form="ooo",
        tax_system="usn",
        usn_tax_object="income",
        vat_status="not_applicable",
        accounting_source="onec",
        money_channels=["bank"],
        month_close_policy="calendar_month_end",
        revenue_recognition_method="accrual",
        is_new_organization=True,
    )
    base.update(kwargs)
    return ProfileSnapshot(**base)


def test_confirm_minimum_complete() -> None:
    result = validate_confirm_readiness(_complete_snapshot())
    assert "_confirm_minimum" not in result.field_errors


def test_confirm_minimum_lists_missing() -> None:
    snap = ProfileSnapshot()
    result = validate_confirm_readiness(snap)
    missing = result.field_errors.get("_confirm_minimum", [])
    assert "org_form" in missing
    assert "tax_system" in missing
    assert "money_channels" in missing


def test_vat_payer_requires_default_rate() -> None:
    snap = _complete_snapshot(vat_status="vat_payer", is_new_organization=True)
    result = validate_confirm_readiness(snap)
    assert "vat_default_rate" in result.field_errors.get("_confirm_minimum", [])
