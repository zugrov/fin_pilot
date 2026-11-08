"""Покрытие активных источников по дате (revenue / cash)."""

from __future__ import annotations

from datetime import date

from app.models.imports import SourceConnection


def sources_coverage_through(
    sources: list[SourceConnection],
    date_to: date,
) -> tuple[bool, date | None]:
    if not sources:
        return False, None
    dates = [item.coverage_through for item in sources]
    if any(item is None for item in dates):
        return False, None
    known = [item for item in dates if item is not None]
    coverage = min(known)
    return coverage >= date_to, coverage
