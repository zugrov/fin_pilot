from datetime import date

from app.domain.org_profile.resolution import resolve_profile_for_period
from app.domain.org_profile.validation import ProfileSnapshot


def _version(eff: str, confirmed: bool, tax: str = "unspecified"):
    return (
        f"id-{eff}",
        date.fromisoformat(eff),
        ProfileSnapshot(tax_system=tax),
        confirmed,
    )


def test_picks_latest_effective_on_or_before_period() -> None:
    versions = [_version("2026-01-01", False), _version("2026-06-01", True, "usn")]
    resolved = resolve_profile_for_period(versions=versions, period_month=date(2026, 8, 1))
    assert resolved is not None
    assert resolved.effective_from == date(2026, 6, 1)
    assert resolved.period_confirmed is True


def test_unconfirmed_latest_makes_period_unconfirmed() -> None:
    versions = [_version("2026-01-01", True, "usn"), _version("2026-06-01", False, "usn")]
    resolved = resolve_profile_for_period(versions=versions, period_month=date(2026, 8, 1))
    assert resolved is not None
    assert resolved.period_confirmed is False


def test_month_boundary() -> None:
    versions = [_version("2026-01-01", True), _version("2026-02-01", False)]
    jan = resolve_profile_for_period(versions=versions, period_month=date(2026, 1, 1))
    feb = resolve_profile_for_period(versions=versions, period_month=date(2026, 2, 1))
    assert jan is not None and jan.version_id == "id-2026-01-01"
    assert feb is not None and feb.version_id == "id-2026-02-01"
