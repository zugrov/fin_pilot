"""CLI одной smoke-записи прогона: пробный запуск, RBAC, автор, повтор, scrub."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from app.tools.fa_r03_persist_run import main
from sqlalchemy import text
from tests.integration.test_fa_r032_persist_run import (
    _company,
    _patch_calculation,
    _report,
    _run_count,
    _settings,
)

SECRET = "pii-purpose-token-cli"
PARTY = "pii-counterparty-token-cli"


def _folder(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "S1_synthetic.txt").write_bytes(b"s1-synthetic")
    (path / "S2_synthetic.xls").write_bytes(b"s2-synthetic")
    return path


def _argv(folder: Path, company_id: str, email: str, *, yes: bool) -> list[str]:
    args = [
        str(folder),
        "--company-id",
        company_id,
        "--period",
        "2026-08",
        "--as-user",
        email,
    ]
    if yes:
        args.append("--yes")
    return args


def _poison(report: dict) -> dict:
    report = dict(report)
    report["purpose"] = SECRET
    report["counterparty"] = PARTY
    matching = dict(report["matching"])
    matching["purpose"] = SECRET
    matching["counterparty_name"] = PARTY
    report["matching"] = matching
    totals = dict(report["control_totals"])
    totals["payer"] = SECRET
    totals["payee"] = PARTY
    report["control_totals"] = totals
    return report


def _demote(admin, tenant_id: str, user_id: str, company_id: str, role: str) -> None:
    with admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE memberships SET role = :role "
                "WHERE tenant_id = :tenant_id AND user_id = :user_id"
            ),
            {"role": role, "tenant_id": tenant_id, "user_id": user_id},
        )
        connection.execute(
            text(
                "INSERT INTO company_access (tenant_id, user_id, company_id) "
                "VALUES (:tenant_id, :user_id, :company_id)"
            ),
            {
                "tenant_id": tenant_id,
                "user_id": user_id,
                "company_id": company_id,
            },
        )


def _unverify(admin, user_id: str) -> None:
    with admin.begin() as connection:
        connection.execute(
            text("UPDATE users SET email_verified_at = NULL WHERE id = :user_id"),
            {"user_id": user_id},
        )


def _rows(admin) -> list:
    with admin.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id::text, created_by_user_id::text, supersedes_run_id::text "
                    "FROM reconciliation_run"
                )
            ).all()
        )


def test_dry_run_writes_nothing(client, admin, app, fake, tmp_path, monkeypatch, capsys) -> None:
    email = "cli-dry-run@example.com"
    _tenant_id, company_id, _user_id = _company(client, admin, app, fake, email)
    _patch_calculation(monkeypatch, [_poison(_report(aligned=True, not_found_bank=0))])
    code = main(
        _argv(_folder(tmp_path), company_id, email, yes=False),
        settings=_settings(app, True),
    )
    captured = capsys.readouterr()
    assert code == 0
    assert _run_count(admin) == 0
    assert "persist=skipped" in captured.out
    assert "matched_pair=1" in captured.out
    assert email not in captured.out
    assert SECRET not in captured.out
    assert PARTY not in captured.out


def test_yes_refuses_when_flag_disabled(
    client, admin, app, fake, tmp_path, capsys
) -> None:
    email = "cli-flag-off@example.com"
    _tenant_id, company_id, _user_id = _company(client, admin, app, fake, email)
    code = main(
        _argv(_folder(tmp_path), company_id, email, yes=True),
        settings=_settings(app, False),
    )
    captured = capsys.readouterr()
    assert code == 1
    assert _run_count(admin) == 0
    assert "RECONCILIATION_RUN_PERSIST_ENABLED" in captured.err
    assert email not in captured.err


@pytest.mark.parametrize("role", ["viewer", "operator"])
def test_yes_refuses_without_finance_write(
    client, admin, app, fake, tmp_path, monkeypatch, capsys, role: str
) -> None:
    email = f"cli-{role}@example.com"
    tenant_id, company_id, user_id = _company(client, admin, app, fake, email)
    _demote(admin, tenant_id, user_id, company_id, role)
    _patch_calculation(monkeypatch, [_report(aligned=True, not_found_bank=0)])
    code = main(
        _argv(_folder(tmp_path), company_id, email, yes=True),
        settings=_settings(app, True),
    )
    captured = capsys.readouterr()
    assert code == 1
    assert _run_count(admin) == 0
    assert "Недостаточно прав" in captured.err
    assert email not in captured.err


def test_yes_refuses_unverified_email(
    client, admin, app, fake, tmp_path, monkeypatch, capsys
) -> None:
    email = "cli-unverified@example.com"
    _tenant_id, _company_id, user_id = _company(client, admin, app, fake, email)
    company_id = _company_id
    _unverify(admin, user_id)
    _patch_calculation(monkeypatch, [_report(aligned=True, not_found_bank=0)])
    code = main(
        _argv(_folder(tmp_path), company_id, email, yes=True),
        settings=_settings(app, True),
    )
    captured = capsys.readouterr()
    assert code == 1
    assert _run_count(admin) == 0
    assert "Подтвердите email" in captured.err
    assert email not in captured.err


def test_yes_refuses_foreign_company(
    client, admin, app, fake, tmp_path, monkeypatch, capsys
) -> None:
    email = "cli-owner-a@example.com"
    _tenant_a, _company_a, _user_a = _company(client, admin, app, fake, email)
    _tenant_b, company_b, _user_b = _company(client, admin, app, fake, "cli-owner-b@example.com")
    _patch_calculation(monkeypatch, [_report(aligned=True, not_found_bank=0)])
    code = main(
        _argv(_folder(tmp_path), company_b, email, yes=True),
        settings=_settings(app, True),
    )
    captured = capsys.readouterr()
    assert code == 1
    assert _run_count(admin) == 0
    assert "Нет доступа к этой организации" in captured.err
    assert email not in captured.err
    assert "cli-owner-b@example.com" not in captured.err


def test_yes_creates_one_row_and_repeat_supersedes(
    client, admin, app, fake, tmp_path, monkeypatch, capsys
) -> None:
    email = "cli-author@example.com"
    _tenant_id, company_id, user_id = _company(client, admin, app, fake, email)
    folder = _folder(tmp_path)
    _patch_calculation(
        monkeypatch,
        [
            _report(aligned=True, not_found_bank=0),
            _report(aligned=True, not_found_bank=0),
        ],
    )
    settings = _settings(app, True)
    first = main(_argv(folder, company_id, email, yes=True), settings=settings)
    first_out = capsys.readouterr().out
    second = main(_argv(folder, company_id, email, yes=True), settings=settings)
    second_out = capsys.readouterr().out
    rows = _rows(admin)
    assert first == 0
    assert second == 0
    assert len(rows) == 2
    original = next(row for row in rows if row.supersedes_run_id is None)
    follow = next(row for row in rows if row.supersedes_run_id is not None)
    assert follow.supersedes_run_id == original.id
    assert original.created_by_user_id == user_id
    assert follow.created_by_user_id == user_id
    assert f"run_id={original.id}" in first_out
    assert f"run_id={follow.id}" in second_out
    assert "persist=written" in first_out
    assert email not in first_out
    assert email not in second_out


def _log_text(mock) -> str:
    parts: list[str] = []
    for call in mock.call_args_list:
        parts.extend(str(arg) for arg in call.args)
    return " ".join(parts)


def test_stdout_and_logs_scrub_pii(
    client, admin, app, fake, tmp_path, monkeypatch, capsys
) -> None:
    email = "cli-secret-user@example.com"
    _tenant_id, company_id, _user_id = _company(client, admin, app, fake, email)
    _patch_calculation(monkeypatch, [_poison(_report(aligned=True, not_found_bank=0))])
    with (
        patch("app.tools.fa_r03_persist_run.logger.info") as info,
        patch("app.tools.fa_r03_persist_run.logger.error") as error,
    ):
        code = main(
            _argv(_folder(tmp_path), company_id, email, yes=True),
            settings=_settings(app, True),
        )
        captured = capsys.readouterr()
        info_text = _log_text(info)
        assert code == 0
        assert _run_count(admin) == 1
        assert "persist=written" in captured.out
        assert "reconciliation_run_cli_recorded" in info_text
        blob = captured.out + captured.err + info_text + _log_text(error)
        assert SECRET not in blob
        assert PARTY not in blob
        assert email not in blob

        def _boom(*_args, **_kwargs):
            raise RuntimeError(f"{SECRET} {email} {PARTY}")

        monkeypatch.setattr(
            "app.tools.fa_r03_persist_run.reconcile_bank_card51_for_company", _boom
        )
        failed = main(
            _argv(_folder(tmp_path / "again"), company_id, email, yes=True),
            settings=_settings(app, True),
        )
        failed_io = capsys.readouterr()
        error_text = _log_text(error)
        assert failed == 1
        assert _run_count(admin) == 1
        assert "запись прогона не выполнена" in failed_io.err
        assert "RuntimeError" in error_text
        failed_blob = failed_io.out + failed_io.err + error_text + info_text
        assert SECRET not in failed_blob
        assert PARTY not in failed_blob
        assert email not in failed_blob
