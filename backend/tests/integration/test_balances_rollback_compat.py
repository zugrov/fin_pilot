import subprocess

import pytest
from app.domain.imports.contracts import ImportFormatError
from app.services import import_service
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import BACKEND
from tests.integration.test_balances_import import BAL_HEADER


@pytest.fixture(autouse=True)
def _guard_test_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


def _93428b7_upload_branch(dataset: str) -> str:
    if dataset == "revenue":
        return "revenue"
    if dataset == "plan":
        return "plan"
    if dataset == "budget":
        return "budget"
    return "cash"


def test_rollback_93428b7_routes_balances_dataset_to_cash_parser() -> None:
    legacy = subprocess.check_output(
        ["git", "show", "93428b7:backend/app/services/import_service.py"],
        cwd=BACKEND.parent,
        text=True,
    )
    assert 'elif connection.dataset == "balances"' not in legacy
    assert 'known = {"cash", "revenue", "plan", "budget"}' in legacy
    assert "commit_balances_batch" not in legacy
    assert _93428b7_upload_branch("balances") == "cash"


def test_rollback_reproduce_balances_csv_misparsed_as_cash(app) -> None:
    """93428b7: upload balances-файла через cash `_parse` → ошибка формата, не balances_reader."""

    class LegacyConnection:
        dataset = "balances"
        format = "csv"
        encoding = "utf-8"

    settings = app.state.settings
    content = BAL_HEADER.encode() + b"main,2026-10-01,10.00,RUB\n"
    with pytest.raises(ImportFormatError):
        import_service._parse(content, LegacyConnection(), "main", settings)
