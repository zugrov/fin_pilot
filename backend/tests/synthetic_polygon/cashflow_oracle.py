"""Ручной ORACLE ОДДС (FA-R06.1 §6.1 и профиль cashflow_sections)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

CompletenessDesign = Literal["full", "preliminary", "unavailable"]

SECTION_CODES = ("operating", "investing", "financing", "technical", "unmapped")


@dataclass(frozen=True)
class SectionOracle:
    code: str
    cash_in: str
    cash_out: str


@dataclass(frozen=True)
class CashflowOracle:
    sections: tuple[SectionOracle, ...]
    net_external: str
    external_count: int
    excluded_internal_amount: str
    design_completeness: CompletenessDesign
    expect_unclassified_flag: bool


def _sections_map(*pairs: tuple[str, str, str]) -> tuple[SectionOracle, ...]:
    by_code = {code: SectionOracle(code, "0.00", "0.00") for code in SECTION_CODES}
    for code, cash_in, cash_out in pairs:
        by_code[code] = SectionOracle(code, cash_in, cash_out)
    return tuple(by_code[code] for code in SECTION_CODES)


OCTOBER_POLYGON_CASHFLOW: dict[str, CashflowOracle] = {
    "services": CashflowOracle(
        sections=_sections_map(("operating", "20000.00", "3000.00")),
        net_external="17000.00",
        external_count=3,
        excluded_internal_amount="0.00",
        design_completeness="full",
        expect_unclassified_flag=False,
    ),
    "retail": CashflowOracle(
        sections=_sections_map(
            ("operating", "15000.00", "2500.00"),
            ("unmapped", "7200.00", "0.00"),
        ),
        net_external="19700.00",
        external_count=3,
        excluded_internal_amount="0.00",
        design_completeness="preliminary",
        expect_unclassified_flag=True,
    ),
    "subscription": CashflowOracle(
        sections=_sections_map(("operating", "4800.00", "0.00")),
        net_external="4800.00",
        external_count=4,
        excluded_internal_amount="0.00",
        design_completeness="full",
        expect_unclassified_flag=False,
    ),
    "cashflow_sections": CashflowOracle(
        sections=_sections_map(
            ("operating", "5000.00", "1200.00"),
            ("financing", "10000.00", "0.00"),
            ("investing", "0.00", "800.00"),
            ("technical", "0.00", "150.00"),
            ("unmapped", "300.00", "0.00"),
        ),
        net_external="13150.00",
        external_count=6,
        excluded_internal_amount="2000.00",
        design_completeness="preliminary",
        expect_unclassified_flag=True,
    ),
}


def design_completeness(
    *,
    has_cash_source: bool,
    coverage_through: date | None,
    date_to: date,
    has_unmapped: bool,
    external_count: int,
) -> CompletenessDesign:
    if not has_cash_source:
        return "unavailable"
    if coverage_through is None or coverage_through < date_to:
        return "preliminary"
    if has_unmapped:
        return "preliminary"
    if external_count == 0:
        return "full"
    return "full"


def section_amounts(body: dict) -> dict[str, tuple[str, str]]:
    return {item["code"]: (item["in"], item["out"]) for item in body["sections"]}
