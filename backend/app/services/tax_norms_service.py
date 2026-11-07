"""
Версии общего справочника налоговых норм (P1a).
Верхние границы 272,5 и 490,5 млн не хранятся — считаются из баз и дефлятора (ADR-003 §4.1).
"""

from datetime import date
from decimal import Decimal

from app.domain.money import (
    money,
    money_str,
    numeric_scale_6_str,
    vat_rate_fraction,
    vat_rate_fraction_str,
)
from app.models.tax_norms import TaxNormVersion
from sqlalchemy import Select, select
from sqlalchemy.orm import Session


def derived_special_cap_5_rub(version: TaxNormVersion) -> Decimal | None:
    """Верхняя граница для ставки 5%: база 250 млн × дефлятор (ADR-003 §4.1)."""
    if version.special_rate_base_5_cap_base_rub is None or version.special_rates_deflator is None:
        return None
    return money(version.special_rate_base_5_cap_base_rub * version.special_rates_deflator)


def derived_special_cap_7_rub(version: TaxNormVersion) -> Decimal | None:
    """Верхняя граница для ставки 7%: база 450 млн × дефлятор (ADR-003 §4.1)."""
    if version.special_rate_base_7_cap_base_rub is None or version.special_rates_deflator is None:
        return None
    return money(version.special_rate_base_7_cap_base_rub * version.special_rates_deflator)


def derived_vat_calc_rates() -> list[dict[str, str]]:
    """Расчётные доли НДС: 22/122, 10/110, 5/105, 7/107."""
    specs = [
        ("22", "122"),
        ("10", "110"),
        ("5", "105"),
        ("7", "107"),
    ]
    out: list[dict[str, str]] = []
    for num_s, den_s in specs:
        num = Decimal(num_s)
        den = Decimal(den_s)
        raw = (num / den) if den != 0 else Decimal("0")
        value = vat_rate_fraction(raw)
        out.append(
            {
                "label": f"{num_s}/{den_s}",
                "numerator": num_s,
                "denominator": den_s,
                "fraction": vat_rate_fraction_str(value),
            }
        )
    return out


def select_version_for_date(stmt: Select, as_of: date) -> Select:
    return (
        stmt.where(TaxNormVersion.valid_from <= as_of)
        .where((TaxNormVersion.valid_to.is_(None)) | (TaxNormVersion.valid_to >= as_of))
        .order_by(TaxNormVersion.valid_from.desc())
        .limit(1)
    )


def get_version_for_date(session: Session, as_of: date) -> TaxNormVersion | None:
    stmt = select_version_for_date(select(TaxNormVersion), as_of)
    return session.execute(stmt).scalar_one_or_none()


def version_to_payload(version: TaxNormVersion) -> dict:
    cap5 = derived_special_cap_5_rub(version)
    cap7 = derived_special_cap_7_rub(version)
    needs_banner = version.status == "needs_review"
    return {
        "id": str(version.id),
        "valid_from": version.valid_from.isoformat(),
        "valid_to": version.valid_to.isoformat() if version.valid_to else None,
        "status": version.status,
        "source_url": version.source_url,
        "verified_at": version.verified_at.isoformat(),
        "verified_by": version.verified_by,
        "notes": version.notes,
        "needs_review_banner": needs_banner,
        "values": {
            "usn_vat_exemption_threshold_rub": money_str(version.usn_vat_exemption_threshold_rub)
            if version.usn_vat_exemption_threshold_rub is not None
            else None,
            "special_rate_base_5_cap_base_rub": money_str(version.special_rate_base_5_cap_base_rub)
            if version.special_rate_base_5_cap_base_rub is not None
            else None,
            "special_rate_base_7_cap_base_rub": money_str(version.special_rate_base_7_cap_base_rub)
            if version.special_rate_base_7_cap_base_rub is not None
            else None,
            "special_rates_deflator": numeric_scale_6_str(version.special_rates_deflator)
            if version.special_rates_deflator is not None
            else None,
            "computed_special_cap_5_rub": money_str(cap5) if cap5 is not None else None,
            "computed_special_cap_7_rub": money_str(cap7) if cap7 is not None else None,
            "vat_rates_general_percent": version.vat_rates_general,
            "vat_rates_special_percent": version.vat_rates_special,
            "vat_calculated_rates": derived_vat_calc_rates(),
        },
    }
