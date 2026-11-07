"""Выбор действующей версии профиля на месяц (ADR-003 §3)."""

from dataclasses import dataclass
from datetime import date

from app.domain.org_profile.support_matrix import SupportAssessment, assess_product_support
from app.domain.org_profile.validation import ProfileSnapshot


@dataclass(frozen=True, slots=True)
class ResolvedOrganizationProfile:
    version_id: str
    effective_from: date
    snapshot: ProfileSnapshot
    is_confirmed: bool
    period_confirmed: bool
    support: SupportAssessment


def resolve_profile_for_period(
    *,
    versions: list[tuple[str, date, ProfileSnapshot, bool]],
    period_month: date,
) -> ResolvedOrganizationProfile | None:
    """
    versions: (id, effective_from, snapshot, is_confirmed) отсортированы по effective_from ASC.
    period_month — первое число месяца периода.
    """
    if period_month.day != 1:
        raise ValueError("period_month must be the first calendar day")

    chosen: tuple[str, date, ProfileSnapshot, bool] | None = None
    for row in versions:
        vid, eff_from, snapshot, confirmed = row
        if eff_from <= period_month:
            chosen = (vid, eff_from, snapshot, confirmed)
        else:
            break

    if chosen is None:
        return None

    vid, eff_from, snapshot, confirmed = chosen
    support = assess_product_support(
        org_form=snapshot.org_form,
        tax_system=snapshot.tax_system,
        accounting_source=snapshot.accounting_source,
    )
    return ResolvedOrganizationProfile(
        version_id=vid,
        effective_from=eff_from,
        snapshot=snapshot,
        is_confirmed=confirmed,
        period_confirmed=confirmed,
        support=support,
    )
