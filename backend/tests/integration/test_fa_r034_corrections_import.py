"""Интеграция FA-R03.4 v1: коррекции после commit cash."""

from pathlib import Path
from uuid import uuid4

from sqlalchemy import text
from tests.integration.test_import_api import (
    FIXTURES,
    _commit,
    _ready,
    _source,
    _upload,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "imports"


def _setup(client, admin, app, fake, tmp_path, email: str) -> tuple[str, str, dict]:
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, email)
    source = _source(client, company_id, wallet_id)
    return company_id, wallet_id, source


def _upload_commit(client, company_id, source_id, content: bytes, name: str) -> None:
    uploaded = _upload(client, company_id, source_id, content, name, uuid4().hex)
    assert uploaded.status_code == 200, uploaded.text
    assert _commit(client, uploaded.json()["id"]).status_code == 200


def test_duplicate_suspect_two_files(client, admin, app, fake, tmp_path) -> None:
    first = (FIXTURES / "cash_ok.csv").read_bytes()
    second = (
        b"external_id,wallet_code,business_date,direction,amount,currency,"
        b"counterparty_inn,counterparty_name,description,document_number,category_code,direction_code\n"
        b"dup-2,main,2026-10-10,in,1500.00,RUB,7700000001,Supplier,invoice payment,15,operating,\n"
    )
    company_id, _, source = _setup(client, admin, app, fake, tmp_path, "dup-a@example.com")
    _upload_commit(client, company_id, source["id"], first, "a.csv")
    _upload_commit(client, company_id, source["id"], second, "b.csv")
    with admin.connect() as connection:
        dup = connection.execute(
            text(
                "SELECT count(*) FROM source_correction_finding f "
                "JOIN companies c ON c.id = f.company_id "
                "WHERE c.id = :cid AND f.kind = 'duplicate_suspect'"
            ),
            {"cid": company_id},
        ).scalar_one()
        txs = connection.execute(
            text("SELECT count(*) FROM cash_transactions WHERE company_id = :cid"),
            {"cid": company_id},
        ).scalar_one()
    assert int(dup) >= 1
    assert int(txs) == 3


def test_period_overlap(client, admin, app, fake, tmp_path) -> None:
    early = (
        b"external_id,wallet_code,business_date,direction,amount,currency,"
        b"counterparty_inn,counterparty_name,description,document_number,category_code,direction_code\n"
        b"p1,main,2026-10-05,out,100.00,RUB,,,test,1,operating,\n"
        b"p2,main,2026-10-12,out,200.00,RUB,,,test,2,operating,\n"
    )
    late = (
        b"external_id,wallet_code,business_date,direction,amount,currency,"
        b"counterparty_inn,counterparty_name,description,document_number,category_code,direction_code\n"
        b"p3,main,2026-10-10,out,150.00,RUB,,,test,3,operating,\n"
        b"p4,main,2026-10-20,out,250.00,RUB,,,test,4,operating,\n"
    )
    company_id, _, source = _setup(client, admin, app, fake, tmp_path, "ov-a@example.com")
    _upload_commit(client, company_id, source["id"], early, "early.csv")
    _upload_commit(client, company_id, source["id"], late, "late.csv")
    with admin.connect() as connection:
        overlap = connection.execute(
            text(
                "SELECT count(*) FROM source_correction_finding "
                "WHERE company_id = :cid AND kind = 'period_overlap'"
            ),
            {"cid": company_id},
        ).scalar_one()
        fp = connection.execute(
            text(
                "SELECT count(*) FROM import_source_fingerprints WHERE company_id = :cid"
            ),
            {"cid": company_id},
        ).scalar_one()
    assert int(fp) == 2
    assert int(overlap) >= 1


def test_internal_transfer_deposit_description(client, admin, app, fake, tmp_path) -> None:
    content = (
        b"external_id,wallet_code,business_date,direction,amount,currency,"
        b"counterparty_inn,counterparty_name,description,document_number,category_code,direction_code\n"
        b"dep-1,main,2026-10-11,out,50000.00,RUB,,,"
        b"\xd0\xa0\xd0\x90\xd0\x97\xd0\x9c\xd0\x95\xd0\xa9\xd0\x95\xd0\x9d\xd0\x98\xd0\x95 "
        b"\xd0\x94\xd0\x95\xd0\x9f\xd0\x9e\xd0\x97\xd0\x98\xd0\xa2\xd0\x90,99,operating,\n"
    )
    company_id, _, source = _setup(client, admin, app, fake, tmp_path, "int-dep@example.com")
    _upload_commit(client, company_id, source["id"], content, "dep.csv")
    with admin.connect() as connection:
        n = connection.execute(
            text(
                "SELECT count(*) FROM source_correction_finding "
                "WHERE company_id = :cid AND kind = 'internal_transfer'"
            ),
            {"cid": company_id},
        ).scalar_one()
    assert int(n) >= 1
