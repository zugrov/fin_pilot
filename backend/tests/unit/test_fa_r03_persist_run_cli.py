"""Маска и allowlist вывода CLI записи прогона."""

from __future__ import annotations

from pathlib import Path

from app.config import Settings
from app.tools.fa_r03_persist_run import main, mask_email, preview_lines

SECRET = "pii-purpose-token-cli"
EMAIL = "cli-secret-user@example.com"


def test_mask_email_hides_local_part_and_domain() -> None:
    masked = mask_email(EMAIL)
    assert masked == "c***"
    assert EMAIL not in masked
    assert "@" not in masked
    assert mask_email("@example.com") == "***"


def test_preview_lines_keep_counters_and_drop_pii() -> None:
    report = {
        "purpose": SECRET,
        "counterparty": "pii-counterparty-token-cli",
        "control_totals": {
            "aligned": False,
            "payer": SECRET,
            "sources": [{"description": SECRET}],
        },
        "daily_chain": {"errors_count": 0, "error_codes": [SECRET]},
        "matching": {
            "matched_pair": 2,
            "group_matched_equivalent": 1,
            "needs_confirmation_groups": 0,
            "not_found_bank": 1,
            "not_found_card": 0,
            "stage1_ambiguous": 0,
            "counterparty_name": SECRET,
            "purpose": SECRET,
        },
    }
    text = "\n".join(
        preview_lines(
            report,
            company_id="11111111-1111-1111-1111-111111111111",
            period="2026-08",
            actor_mask="c***",
            flag_on=True,
        )
    )
    assert "matched_pair=2" in text
    assert "not_found_bank=1" in text
    assert "status=completed_with_warnings" in text
    assert "quality_flag=bank_card51_discrepancy" in text
    assert SECRET not in text
    assert "pii-counterparty-token-cli" not in text
    assert EMAIL not in text


def test_dry_run_does_not_open_engine(tmp_path: Path, monkeypatch, capsys) -> None:
    folder = tmp_path / "samples"
    folder.mkdir()
    (folder / "S1_synthetic.txt").write_bytes(b"s1")
    (folder / "S2_synthetic.xls").write_bytes(b"s2")

    def _refuse_engine(*_args, **_kwargs):
        raise AssertionError("БД не должна открываться")

    monkeypatch.setattr("app.tools.fa_r03_persist_run.create_engine", _refuse_engine)
    monkeypatch.setattr(
        "app.tools.fa_r03_persist_run.build_bank_card51_report",
        lambda *_args, **_kwargs: {
            "purpose": SECRET,
            "control_totals": {"aligned": True},
            "daily_chain": {"errors_count": 0},
            "matching": {
                "matched_pair": 1,
                "group_matched_equivalent": 0,
                "needs_confirmation_groups": 0,
                "not_found_bank": 0,
                "not_found_card": 0,
                "stage1_ambiguous": 0,
            },
        },
    )
    code = main(
        [
            str(folder),
            "--company-id",
            "11111111-1111-1111-1111-111111111111",
            "--period",
            "2026-08",
            "--as-user",
            EMAIL,
        ],
        settings=Settings(reconciliation_run_persist_enabled=True),
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "persist=skipped" in captured.out
    assert "matched_pair=1" in captured.out
    assert SECRET not in captured.out
    assert EMAIL not in captured.out
    assert EMAIL not in captured.err


def test_yes_without_flag_refuses_before_database(tmp_path: Path, monkeypatch, capsys) -> None:
    def _refuse_engine(*_args, **_kwargs):
        raise AssertionError("БД не должна открываться")

    monkeypatch.setattr("app.tools.fa_r03_persist_run.create_engine", _refuse_engine)
    code = main(
        [
            str(tmp_path),
            "--company-id",
            "11111111-1111-1111-1111-111111111111",
            "--period",
            "2026-08",
            "--as-user",
            EMAIL,
            "--yes",
        ],
        settings=Settings(reconciliation_run_persist_enabled=False),
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "RECONCILIATION_RUN_PERSIST_ENABLED" in captured.err
    assert EMAIL not in captured.err
    assert EMAIL not in captured.out
