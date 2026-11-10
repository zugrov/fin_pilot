"""Provenance: сбой после commit импорта не откатывает проведение."""

from unittest.mock import patch
from uuid import uuid4

from app.services import import_service
from sqlalchemy import text
from tests.integration.test_import_api import (
    FIXTURES,
    _commit,
    _ready,
    _source,
    _upload,
)


def test_provenance_failure_keeps_import_committed(
    client, admin, app, fake, tmp_path, monkeypatch
) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "prov-fail@example.com")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("provenance synthetic failure")

    monkeypatch.setattr(
        "app.services.provenance_service.register_batch_fingerprint",
        _boom,
    )
    source = _source(client, company_id, wallet_id)
    content = (FIXTURES / "cash_ok.csv").read_bytes()
    uploaded = _upload(client, company_id, source["id"], content, "cash.csv", uuid4().hex)
    batch_id = uploaded.json()["id"]
    with patch.object(import_service.logger, "exception") as logged:
        committed = _commit(client, batch_id)
        assert committed.status_code == 200, committed.text
        logged.assert_called()
        assert logged.call_args[0][0] == "import_provenance_failed batch_id=%s"
        assert str(logged.call_args[0][1]) == batch_id

    assert committed.json()["status"] in {"completed", "completed_with_errors"}

    with admin.connect() as connection:
        tx_count = connection.execute(text("SELECT count(*) FROM cash_transactions")).scalar_one()
        fp_count = connection.execute(
            text("SELECT count(*) FROM import_source_fingerprints")
        ).scalar_one()
        batch_status = connection.execute(
            text("SELECT status FROM import_batches WHERE id = :id"),
            {"id": batch_id},
        ).scalar_one()
    assert int(tx_count) >= 1
    assert int(fp_count) == 0
    assert batch_status in {"completed", "completed_with_errors"}
