"""Безопасность путей локальных образцов FA-R03."""

from __future__ import annotations

from pathlib import Path

from app.services.bank_card_reconciliation_service import resolve_local_sample_folder


def test_resolve_rejects_path_outside_base_via_symlink(tmp_path: Path) -> None:
    base = tmp_path / "var"
    base.mkdir()
    samples = base / "fa-r03-client-samples"
    samples.mkdir()
    (samples / "S1_test.txt").write_text("x", encoding="utf-8")
    outside = tmp_path / "outside.xls"
    outside.write_bytes(b"x")
    link = samples / "S2_evil.xls"
    link.symlink_to(outside)

    folder = resolve_local_sample_folder(str(base), 2026, 9)
    assert folder is None


def test_resolve_accepts_valid_layout(tmp_path: Path) -> None:
    base = tmp_path / "var"
    samples = base / "fa-r03-client-samples"
    samples.mkdir(parents=True)
    (samples / "S1_bank.txt").write_text("x", encoding="utf-8")
    (samples / "S2_card.xls").write_bytes(b"x")

    folder = resolve_local_sample_folder(str(base), 2026, 9)
    assert folder is not None
    assert folder.s1.name.startswith("S1_")
