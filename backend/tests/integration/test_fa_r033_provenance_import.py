from uuid import uuid4

from sqlalchemy import text
from tests.integration.test_import_api import (
    FIXTURES,
    _commit,
    _ready,
    _source,
    _upload,
)


def test_commit_writes_fingerprint_and_lineage(client, admin, app, fake, tmp_path) -> None:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "prov@example.com")
    source = _source(client, company_id, wallet_id)
    content = (FIXTURES / "cash_ok.csv").read_bytes()
    uploaded = _upload(client, company_id, source["id"], content, "cash.csv", uuid4().hex)
    assert uploaded.status_code == 200, uploaded.text
    batch_id = uploaded.json()["id"]
    committed = _commit(client, batch_id)
    assert committed.status_code == 200, committed.text
    with admin.connect() as connection:
        fp_count = connection.execute(
            text("SELECT count(*) FROM import_source_fingerprints WHERE import_batch_id = :b"),
            {"b": batch_id},
        ).scalar_one()
        lin_count = connection.execute(
            text(
                "SELECT count(*) FROM import_row_lineage l "
                "JOIN raw_import_rows r ON r.id = l.raw_import_row_id "
                "WHERE r.batch_id = :b"
            ),
            {"b": batch_id},
        ).scalar_one()
    assert int(fp_count) == 1
    assert int(lin_count) >= 1
