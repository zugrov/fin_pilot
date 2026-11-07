"""Матрица поддержки ADR-003 §7 (форма × режим × источник)."""

from dataclasses import dataclass
from typing import Literal

SupportLevel = Literal["supported", "partial", "unsupported"]

UNSUPPORTED_TAX_SYSTEMS = frozenset({"ausn", "psn", "eshn", "self_employed"})


@dataclass(frozen=True, slots=True)
class SupportAssessment:
    level: SupportLevel
    code: str | None


def assess_product_support(
    *,
    org_form: str,
    tax_system: str,
    accounting_source: str,
) -> SupportAssessment:
    if tax_system in UNSUPPORTED_TAX_SYSTEMS:
        return SupportAssessment("unsupported", "tax_system_not_supported")

    if org_form not in {"ip", "ooo"}:
        if org_form in {"unspecified", "unknown"}:
            return SupportAssessment("partial", "org_form_unspecified")
        return SupportAssessment("partial", "org_form_limited_support")

    if tax_system not in {"usn", "osno"}:
        if tax_system in {"unspecified", "unknown"}:
            return SupportAssessment("partial", "tax_system_unspecified")
        return SupportAssessment("partial", "tax_system_limited_support")

    return _matrix_cell(org_form, tax_system, accounting_source)


def _matrix_cell(org_form: str, tax_system: str, accounting_source: str) -> SupportAssessment:
    if accounting_source in {"unspecified", "unknown"}:
        return SupportAssessment("partial", "accounting_source_unspecified")

    if accounting_source == "book_csv":
        if tax_system == "osno":
            return SupportAssessment("unsupported", "osno_book_csv_unsupported")
        return SupportAssessment("partial", "book_csv_limited")

    if accounting_source == "onec":
        if tax_system == "usn":
            return SupportAssessment("supported", None)
        return SupportAssessment("partial", "osno_limited_vat")

    if accounting_source == "cloud":
        return SupportAssessment("partial", "cloud_export_required")

    return SupportAssessment("partial", "accounting_source_unspecified")
