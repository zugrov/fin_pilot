import hashlib
import os
import sys
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import backup as backup_script
import psycopg
import restore as restore_script
from backup import RESTORE_DATABASE, create_backup
from restore import restore_backup
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import (
    INTEGRATION_PG_HOST,
    INTEGRATION_PG_PORT,
    login,
    open_workspace,
    pay,
    register_and_verify,
)


def _bind_pg_client_tools(monkeypatch, admin) -> None:
    """PG_DUMP/PG_RESTORE той же major-версии, что сервер finpilot_test (без смены scripts/)."""
    if os.environ.get("PG_DUMP"):
        return
    with admin.connect() as connection:
        major = connection.execute(
            text("SELECT split_part(current_setting('server_version'), '.', 1)")
        ).scalar_one()
    candidates = (
        Path(f"/Applications/Postgres.app/Contents/Versions/{major}/bin"),
        Path.home() / ".local" / f"pg{major}" / "bin",
    )
    for root in candidates:
        dump = root / "pg_dump"
        restore = root / "pg_restore"
        if dump.is_file() and restore.is_file():
            monkeypatch.setenv("PG_DUMP", str(dump))
            monkeypatch.setenv("PG_RESTORE", str(restore))
            return


def test_restore_keeps_amount_and_attachment(
    client, admin, app, fake, tmp_path, monkeypatch
) -> None:
    assert_finpilot_test_database(admin)
    monkeypatch.setenv("BACKUP_PASSPHRASE", "backup-passphrase-1")
    # CLI backup запрещает 5432; integration использует тот же порт, что TEST_PG_PORT/fixtures.
    allow_test_port = lambda _port: None
    monkeypatch.setattr(backup_script, "assert_port", allow_test_port)
    monkeypatch.setattr(restore_script, "assert_port", allow_test_port)
    _bind_pg_client_tools(monkeypatch, admin)
    storage = tmp_path / "imports"
    storage.mkdir()
    marker = storage / "marker.txt"
    marker.write_bytes(b"statement-body")
    digest = hashlib.sha256(marker.read_bytes()).hexdigest()
    app.state.settings.import_storage_dir = str(storage)
    register_and_verify(client, admin, "backup@example.com")
    login(client, "backup@example.com")
    tenant_id = open_workspace(client, "Копия")
    company = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Фирма", "kind": "company"},
    )
    assert company.status_code == 200, company.text
    company_id = company.json()["id"]
    pay(client, app, fake, 1, "month")
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    wallet = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Расчётный", "type": "bank", "code": "main"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert wallet.status_code == 200, wallet.text
    opened = client.post(
        f"/api/v1/wallets/{wallet.json()['id']}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+00:00", "amount": "0.00"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert opened.status_code == 200, opened.text
    created = client.post(
        f"/api/v1/companies/{company_id}/transactions",
        json={
            "wallet_id": wallet.json()["id"],
            "business_date": "2026-10-10",
            "occurred_at": "2026-10-10T12:00:00+00:00",
            "direction": "in",
            "amount": "10.00",
            "description": "backup-marker",
            "status": "posted",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    archive = tmp_path / "copy.enc"
    restored = tmp_path / "restored"
    create_backup(
        host=INTEGRATION_PG_HOST,
        port=INTEGRATION_PG_PORT,
        database="finpilot_test",
        storage_dir=storage,
        output=archive,
        passphrase="backup-passphrase-1",
    )
    assert archive.is_file()
    assert b"backup-marker" not in archive.read_bytes()
    try:
        restore_backup(
            host=INTEGRATION_PG_HOST,
            port=INTEGRATION_PG_PORT,
            storage_dir=restored,
            source=archive,
            passphrase="backup-passphrase-1",
        )
        restore_url = (
            f"postgresql://{INTEGRATION_PG_HOST}:{INTEGRATION_PG_PORT}/{RESTORE_DATABASE}"
        )
        with psycopg.connect(restore_url) as connection:
            amount = connection.execute(
                "SELECT amount::text FROM cash_transactions WHERE description = 'backup-marker'"
            ).fetchone()
        assert amount is not None
        assert amount[0] == "10.00"
        restored_file = restored / "marker.txt"
        assert hashlib.sha256(restored_file.read_bytes()).hexdigest() == digest
    finally:
        admin_url = f"postgresql://{INTEGRATION_PG_HOST}:{INTEGRATION_PG_PORT}/postgres"
        with psycopg.connect(admin_url, autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (RESTORE_DATABASE,),
            )
            connection.execute(f"DROP DATABASE IF EXISTS {RESTORE_DATABASE}")
