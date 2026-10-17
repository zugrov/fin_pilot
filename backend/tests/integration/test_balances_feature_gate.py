from uuid import uuid4

import pytest
from tests.integration.balances_test_util import (
    assert_finpilot_test_database,
    opening_total,
)
from tests.integration.conftest import login, open_workspace, pay, register_and_verify
from tests.integration.test_balances_import import (
    BAL_HEADER,
    _balances_source,
    _commit,
    _ready,
)
from tests.integration.test_import_api import HEADER, _source, _upload

CASH_ROW = "ext-1,main,2026-10-01,in,100.00,RUB,7700000000,OOO Test,Payment,1,,\n"


@pytest.fixture(autouse=True)
def _guard_test_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


def _assert_gate(resp) -> None:
    assert resp.status_code == 503, resp.text
    assert resp.json()["code"] == "balances_import_disabled"


def test_balances_import_disabled_by_default(app) -> None:
    assert app.state.settings.balances_import_enabled is False


def test_balances_create_source_blocked_when_disabled(client, admin, app, fake, tmp_path) -> None:
    app.state.settings.balances_import_enabled = False
    company_id, _ = _ready(client, admin, app, fake, tmp_path, "gate-off@example.com")
    created = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": "Остатки",
            "type": "file",
            "namespace": "balances",
            "format": "csv",
            "dataset": "balances",
        },
    )
    _assert_gate(created)


def test_balances_enabled_path_works(client, admin, app, fake, tmp_path) -> None:
    app.state.settings.balances_import_enabled = True
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "gate-on@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,1000.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "g1")
    assert uploaded.status_code == 200, uploaded.text
    committed = _commit(client, uploaded.json()["id"], uploaded.json()["preview_token"])
    assert committed.status_code == 200, committed.text
    assert opening_total(admin, wallet_id) == 1


def test_balances_disabled_after_preview_blocks_mutations(
    client, admin, app, fake, tmp_path
) -> None:
    app.state.settings.balances_import_enabled = True
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "gate-toggle@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,500.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "g2")
    assert uploaded.status_code == 200, uploaded.text
    batch_id = uploaded.json()["id"]
    preview_token = uploaded.json()["preview_token"]

    app.state.settings.balances_import_enabled = False

    blocked_upload = _upload(
        client, company_id, source["id"], content, "balances.csv", "g2b"
    )
    _assert_gate(blocked_upload)

    refresh = client.post(f"/api/v1/imports/{batch_id}/refresh-preview")
    _assert_gate(refresh)

    commit = _commit(client, batch_id, preview_token)
    _assert_gate(commit)

    preview = client.get(f"/api/v1/imports/{batch_id}/preview")
    assert preview.status_code == 200, preview.text
    assert opening_total(admin, wallet_id) == 0


def test_balances_completed_batch_get_ok_commit_blocked(
    client, admin, app, fake, tmp_path
) -> None:
    app.state.settings.balances_import_enabled = True
    company_id, _ = _ready(client, admin, app, fake, tmp_path, "gate-done@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,100.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "g3")
    batch_id = uploaded.json()["id"]
    token = uploaded.json()["preview_token"]
    assert _commit(client, batch_id, token).status_code == 200

    app.state.settings.balances_import_enabled = False
    assert client.get(f"/api/v1/imports/{batch_id}/preview").status_code == 200
    _assert_gate(_commit(client, batch_id, token))


def test_balances_disabled_upload_has_no_side_effects(
    client, admin, app, fake, tmp_path
) -> None:
    app.state.settings.balances_import_enabled = True
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "gate-side@example.com")
    source = _balances_source(client, company_id)
    app.state.settings.balances_import_enabled = False
    content = BAL_HEADER.encode() + b"main,2026-10-01,900.00,RUB\n"
    before_openings = opening_total(admin, wallet_id)
    resp = _upload(client, company_id, source["id"], content, "balances.csv", "g4")
    _assert_gate(resp)
    assert opening_total(admin, wallet_id) == before_openings


def test_balances_disabled_cash_import_and_manual_opening_ok(
    client, admin, app, fake, tmp_path
) -> None:
    app.state.settings.balances_import_enabled = False
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "gate-cash@example.com")
    cash_source = _source(client, company_id, wallet_id)
    uploaded = _upload(
        client,
        company_id,
        cash_source["id"],
        HEADER.encode() + CASH_ROW.encode(),
        "cash.csv",
        "g5",
    )
    assert uploaded.status_code == 200, uploaded.text
    opening = client.post(
        f"/api/v1/wallets/{wallet_id}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+03:00", "amount": "1.00"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert opening.status_code == 200, opening.text


def test_balances_reenabled_commit_not_automatic(
    client, admin, app, fake, tmp_path
) -> None:
    app.state.settings.balances_import_enabled = True
    company_id, wallet_id = _ready(client, admin, app, fake, tmp_path, "gate-re@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,250.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "g6")
    batch_id = uploaded.json()["id"]
    token = uploaded.json()["preview_token"]

    app.state.settings.balances_import_enabled = False
    _assert_gate(_commit(client, batch_id, token))
    assert opening_total(admin, wallet_id) == 0

    app.state.settings.balances_import_enabled = True
    committed = _commit(client, batch_id, token)
    assert committed.status_code == 200, committed.text
    assert opening_total(admin, wallet_id) == 1


def test_balances_gate_after_not_found_for_foreign_batch(
    client, admin, app, fake, tmp_path
) -> None:
    app.state.settings.balances_import_enabled = True
    company_id, _ = _ready(client, admin, app, fake, tmp_path, "gate-a@example.com")
    source = _balances_source(client, company_id)
    content = BAL_HEADER.encode() + b"main,2026-10-01,10.00,RUB\n"
    uploaded = _upload(client, company_id, source["id"], content, "balances.csv", "g7")
    batch_id = uploaded.json()["id"]
    token = uploaded.json()["preview_token"]

    register_and_verify(client, admin, "gate-b@example.com")
    login(client, "gate-b@example.com")
    tenant_b = open_workspace(client, "B")
    company_b = client.post(
        f"/api/v1/workspaces/{tenant_b}/companies",
        json={"name": "Другая", "kind": "company"},
    )
    assert company_b.status_code == 200
    pay(client, app, fake, 1, "month")
    activate = client.post(f"/api/v1/billing/companies/{company_b.json()['id']}/activate")
    assert activate.status_code == 200

    app.state.settings.balances_import_enabled = False
    foreign = _commit(client, batch_id, token)
    assert foreign.status_code == 404, foreign.text
    assert foreign.json()["code"] == "not_found"
