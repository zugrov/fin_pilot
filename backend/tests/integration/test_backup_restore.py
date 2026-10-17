import hashlib
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import psycopg
from backup import RESTORE_DATABASE, create_backup
from restore import restore_backup
from tests.integration.conftest import login, open_workspace, pay, register_and_verify


def test_restore_keeps_amount_and_attachment(
    client, admin, app, fake, tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("BACKUP_PASSPHRASE", "backup-passphrase-1")
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
        host="127.0.0.1",
        port=5433,
        database="finpilot_test",
        storage_dir=storage,
        output=archive,
        passphrase="backup-passphrase-1",
    )
    assert archive.is_file()
    assert b"backup-marker" not in archive.read_bytes()
    try:
        restore_backup(
            host="127.0.0.1",
            port=5433,
            storage_dir=restored,
            source=archive,
            passphrase="backup-passphrase-1",
        )
        with psycopg.connect(f"postgresql://127.0.0.1:5433/{RESTORE_DATABASE}") as connection:
            amount = connection.execute(
                "SELECT amount::text FROM cash_transactions WHERE description = 'backup-marker'"
            ).fetchone()
        assert amount is not None
        assert amount[0] == "10.00"
        restored_file = restored / "marker.txt"
        assert hashlib.sha256(restored_file.read_bytes()).hexdigest() == digest
    finally:
        with psycopg.connect("postgresql://127.0.0.1:5433/postgres", autocommit=True) as connection:
            connection.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
                (RESTORE_DATABASE,),
            )
            connection.execute(f"DROP DATABASE IF EXISTS {RESTORE_DATABASE}")
