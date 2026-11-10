from unittest import mock
from uuid import uuid4

from sqlalchemy import text
from tests.integration.test_import_api import (
    FIXTURES,
    _commit,
    _ready,
    _source,
    _upload,
)


def test_correction_scan_failure_does_not_break_commit(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "corr-hook@example.com")
    source = _source(client, company_id, wallet_id)
    content = (FIXTURES / "cash_ok.csv").read_bytes()
    uploaded = _upload(client, company_id, source["id"], content, "cash.csv", uuid4().hex)
    batch_id = uploaded.json()["id"]
    target = "app.services.correction_service.scan_cash_corrections_after_import"
    with mock.patch(target, side_effect=RuntimeError("correction_boom")):
        with mock.patch("app.services.import_service.logger") as log_mock:
            committed = _commit(client, batch_id)
    assert committed.status_code == 200, committed.text
    with admin.connect() as connection:
        cash = connection.execute(
            text("SELECT count(*) FROM cash_transactions WHERE company_id = :c"),
            {"c": company_id},
        ).scalar_one()
        fp = connection.execute(
            text(
                "SELECT count(*) FROM import_source_fingerprints fp "
                "JOIN import_batches b ON b.id = fp.import_batch_id "
                "WHERE b.company_id = :c"
            ),
            {"c": company_id},
        ).scalar_one()
    assert int(cash) >= 1
    assert int(fp) == 0
    log_mock.exception.assert_called()
