"""Единое определение «неразнесённой» операции для ОДДС и сводки классификации."""

from __future__ import annotations

SECTIONS = ("operating", "investing", "financing", "technical", "unmapped")
UNMAPPED = "unmapped"

# Перевод внутри фирмы, подтверждённый связкой ног.
INTERNAL_KIND = "internal"
LINKED_STATUS = "linked"


def is_internal_transfer(kind: str | None, status: str | None) -> bool:
    """Пара ног — подтверждённый перевод внутри одной фирмы."""
    return kind == INTERNAL_KIND and status == LINKED_STATUS


def section_of(category_section: str | None) -> str:
    """Секция ОДДС по разделу категории; всё неизвестное попадает в unmapped."""
    if category_section in SECTIONS:
        return str(category_section)
    return UNMAPPED


def is_unclassified(
    category_section: str | None,
    *,
    transfer_kind: str | None = None,
    transfer_status: str | None = None,
) -> bool:
    """Операция без раздела ОДДС; внутренний перевод не считается неразнесённым."""
    if is_internal_transfer(transfer_kind, transfer_status):
        return False
    return section_of(category_section) == UNMAPPED
