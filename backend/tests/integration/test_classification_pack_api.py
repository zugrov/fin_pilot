"""Каталог classification pack ru-bank-clientbank v1."""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import login, open_workspace, pay, register_and_verify
from tests.synthetic_polygon.cashflow_oracle import section_amounts

PACK = "ru-bank-clientbank"
VERSION = "1.0.0"
PERIOD = ("2026-10-01", "2026-10-31")

HEADER = (
    "external_id,wallet_code,business_date,direction,amount,currency,"
    "counterparty_inn,counterparty_name,description,document_number,category_code,direction_code\n"
)


@pytest.fixture(autouse=True)
def _guard_test_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


@pytest.fixture(autouse=True)
def _packs_enabled(app):
    app.state.settings.classification_packs_enabled = True
    app.state.settings.balances_import_enabled = True


def _company(client: TestClient, admin, app, fake, tmp_path, email: str) -> str:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Pack Co")
    pay(client, app, fake, 1, "month")
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Pack Co", "kind": "company", "timezone": "Europe/Moscow"},
    )
    assert created.status_code == 200, created.text
    company_id = created.json()["id"]
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return company_id


def _tenant_with_companies(
    client: TestClient, admin, app, fake, tmp_path, email: str, count: int
) -> tuple[str, list[str]]:
    """Один tenant и несколько фирм в нём (оплата на `count` фирм)."""
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Pack Multi Co")
    pay(client, app, fake, count, "month")
    company_ids: list[str] = []
    for index in range(count):
        created = client.post(
            f"/api/v1/workspaces/{tenant_id}/companies",
            json={
                "name": f"Pack Co {index + 1}",
                "kind": "company",
                "timezone": "Europe/Moscow",
            },
        )
        assert created.status_code == 200, created.text
        company_id = created.json()["id"]
        activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
        assert activated.status_code == 200, activated.text
        company_ids.append(company_id)
    return tenant_id, company_ids


def _wallet(client: TestClient, company_id: str) -> str:
    created = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Main", "type": "bank", "code": "main"},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _source(client: TestClient, company_id: str, wallet_id: str, namespace: str) -> str:
    created = client.post(
        f"/api/v1/companies/{company_id}/sources",
        json={
            "name": f"cash-{namespace}",
            "type": "file",
            "namespace": namespace,
            "format": "csv",
            "dataset": "cash",
            "wallet_id": wallet_id,
        },
    )
    assert created.status_code == 200, created.text
    return created.json()["id"]


def _import_csv(client: TestClient, company_id: str, source_id: str, rows: str) -> None:
    body = HEADER + rows
    uploaded = client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": source_id},
        files={"upload": ("cash.csv", body.encode("utf-8"), "text/csv")},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert uploaded.status_code == 200, uploaded.text
    committed = client.post(f"/api/v1/imports/{uploaded.json()['id']}/commit")
    assert committed.status_code == 200, committed.text


def _pack_url(company_id: str, suffix: str) -> str:
    return f"/api/v1/companies/{company_id}/classification-packs/{PACK}/{VERSION}/{suffix}"


def test_flag_disabled_returns_404(client, admin, app, fake, tmp_path) -> None:
    app.state.settings.classification_packs_enabled = False
    company_id = _company(client, admin, app, fake, tmp_path, "pack-off@example.com")
    response = client.post(
        _pack_url(company_id, "preview"),
        json={"date_from": PERIOD[0], "date_to": PERIOD[1]},
    )
    assert response.status_code == 404


def test_install_apply_classifies_synthetic_rows(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "pack-main@example.com")
    wallet_id = _wallet(client, company_id)
    ns = uuid4().hex[:8]
    source_id = _source(client, company_id, wallet_id, ns)
    rows = (
        "d1,main,2026-10-05,in,1000.00,RUB,,,ПРОЦЕНТОВ ПО ДЕПОЗ за период,,,\n"
        "d2,main,2026-10-06,in,2000.00,RUB,,,Терминал № 1,,,\n"
        "d3,main,2026-10-07,out,300.00,RUB,,,ЗАРПЛАТА,,,\n"
        "d4,main,2026-10-08,out,50.00,RUB,,,НДС,,,\n"
        "d5,main,2026-10-09,out,40.00,RUB,,,КОМИССИЯ,,,\n"
        "d6,main,2026-10-10,out,100.00,RUB,,,ПРОЧИЕ ВЫДАЧ,,,\n"
        "d7,main,2026-10-11,in,500.00,RUB,,,ОПЛАТА по счёту,,,\n"
        "d8,main,2026-10-12,in,77.00,RUB,,,,,\n"
    )
    _import_csv(client, company_id, source_id, rows)

    preview = client.post(
        _pack_url(company_id, "preview"),
        json={"date_from": PERIOD[0], "date_to": PERIOD[1]},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["unmapped_count"] >= 1

    installed = client.post(
        _pack_url(company_id, "install"),
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert installed.status_code == 200, installed.text
    assert len(installed.json()["created"]) == 32

    again = client.post(
        _pack_url(company_id, "install"),
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert again.status_code == 200, again.text
    assert len(again.json()["skipped"]) == 32
    assert again.json()["created"] == []

    applied = client.post(_pack_url(company_id, "apply"))
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] >= 7

    cf = client.get(
        f"/api/v1/companies/{company_id}/cashflow?date_from={PERIOD[0]}&date_to={PERIOD[1]}"
    )
    assert cf.status_code == 200, cf.text
    amounts = section_amounts(cf.json())
    assert amounts["investing"][0] == "1000.00"
    assert amounts["operating"][0] == "2500.00"
    assert amounts["operating"][1] == "390.00"
    assert amounts["technical"][1] == "100.00"
    assert amounts["unmapped"][0] == "77.00"

    disabled = client.post(_pack_url(company_id, "disable"))
    assert disabled.status_code == 200, disabled.text
    assert len(disabled.json()["disabled_rule_ids"]) == 32


def test_user_rule_priority_over_pack(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "pack-prio@example.com")
    user_rule = client.post(
        f"/api/v1/companies/{company_id}/classification-rules",
        json={
            "name": "User operating catch deposit phrase",
            "priority": 5,
            "conditions": {"description_contains": "ПРОЦЕНТОВ ПО ДЕПОЗ"},
            "category_code": "operating",
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert user_rule.status_code == 200, user_rule.text
    wallet_id = _wallet(client, company_id)
    source_id = _source(client, company_id, wallet_id, uuid4().hex[:8])
    _import_csv(
        client,
        company_id,
        source_id,
        "x1,main,2026-10-05,in,1000.00,RUB,,,ПРОЦЕНТОВ ПО ДЕПОЗ,,,\n",
    )

    preview = client.post(
        _pack_url(company_id, "preview"),
        json={"date_from": PERIOD[0], "date_to": PERIOD[1]},
    )
    assert preview.status_code == 200, preview.text
    intersections = preview.json()["intersections_with_existing"]
    assert intersections

    client.post(
        _pack_url(company_id, "install"),
        headers={"Idempotency-Key": uuid4().hex},
    )
    from tests.synthetic_polygon.classification_harness import apply_rule_to_posted

    apply_rule_to_posted(client, company_id, user_rule.json()["id"])
    client.post(_pack_url(company_id, "apply"))
    cf = client.get(
        f"/api/v1/companies/{company_id}/cashflow?date_from={PERIOD[0]}&date_to={PERIOD[1]}"
    )
    amounts = section_amounts(cf.json())
    assert amounts["operating"][0] == "1000.00"
    assert amounts["investing"][0] == "0.00"


def test_other_company_install_404(client, admin, app, fake, tmp_path) -> None:
    company_a = _company(client, admin, app, fake, tmp_path, "pack-a@example.com")
    company_b = _company(client, admin, app, fake, tmp_path, "pack-b@example.com")
    client.post(
        _pack_url(company_a, "install"),
        headers={"Idempotency-Key": uuid4().hex},
    )
    # company_b has no install — disable returns 404
    response = client.post(_pack_url(company_b, "disable"))
    assert response.status_code == 404


def test_two_companies_one_tenant_are_isolated(client, admin, app, fake, tmp_path) -> None:
    _tenant_id, (company_a, company_b) = _tenant_with_companies(
        client, admin, app, fake, tmp_path, "pack-same-tenant@example.com", 2
    )
    wallet_a = _wallet(client, company_a)
    wallet_b = _wallet(client, company_b)
    rows = "iso-1,main,2026-10-07,out,300.00,RUB,,,ЗАРПЛАТА,,,\n"
    source_a = _source(client, company_a, wallet_a, uuid4().hex[:8])
    source_b = _source(client, company_b, wallet_b, uuid4().hex[:8])
    _import_csv(client, company_a, source_a, rows)
    _import_csv(client, company_b, source_b, rows)

    installed_a = client.post(
        _pack_url(company_a, "install"),
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert installed_a.status_code == 200, installed_a.text
    assert len(installed_a.json()["created"]) == 32

    # Установка на A не делает набор установленным для B.
    disabled_b = client.post(_pack_url(company_b, "disable"))
    assert disabled_b.status_code == 404
    applied_b = client.post(_pack_url(company_b, "apply"))
    assert applied_b.status_code == 404

    installed_b = client.post(
        _pack_url(company_b, "install"),
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert installed_b.status_code == 200, installed_b.text
    assert len(installed_b.json()["created"]) == 32
    assert installed_b.json()["skipped"] == []

    applied_a = client.post(_pack_url(company_a, "apply"))
    assert applied_a.status_code == 200, applied_a.text
    assert applied_a.json()["applied"] == 1

    disabled_b_after = client.post(_pack_url(company_b, "disable"))
    assert disabled_b_after.status_code == 200, disabled_b_after.text
    assert len(disabled_b_after.json()["disabled_rule_ids"]) == 32

    # Отключение на B не затрагивает правила A: применение A снова сработает после снятия категории.
    cf_a = client.get(
        f"/api/v1/companies/{company_a}/cashflow?date_from={PERIOD[0]}&date_to={PERIOD[1]}"
    )
    assert cf_a.status_code == 200, cf_a.text
    assert section_amounts(cf_a.json())["operating"][1] == "300.00"

    disabled_a = client.post(_pack_url(company_a, "disable"))
    assert disabled_a.status_code == 200, disabled_a.text
    assert len(disabled_a.json()["disabled_rule_ids"]) == 32


def test_repeat_install_same_version_has_no_duplicates(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "pack-repeat@example.com")
    first = client.post(
        _pack_url(company_id, "install"),
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        _pack_url(company_id, "install"),
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert second.status_code == 200, second.text
    third = client.post(
        _pack_url(company_id, "install"),
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert third.status_code == 200, third.text
    assert third.json()["created"] == []
    assert len(third.json()["skipped"]) == 32

    rules = client.get(f"/api/v1/companies/{company_id}/classification-rules")
    assert rules.status_code == 200, rules.text
    pack_rules = [row for row in rules.json()["rules"] if row["name"].startswith("[pack:")]
    assert len(pack_rules) == 32

    disabled = client.post(_pack_url(company_id, "disable"))
    assert disabled.status_code == 200, disabled.text
    assert len(set(disabled.json()["disabled_rule_ids"])) == 32
    assert len(disabled.json()["disabled_rule_ids"]) == 32


def test_foreign_company_install_paths_404(client, admin, app, fake, tmp_path) -> None:
    owner_company = _company(client, admin, app, fake, tmp_path, "pack-owner@example.com")
    client.post(
        _pack_url(owner_company, "install"),
        headers={"Idempotency-Key": uuid4().hex},
    )
    foreign_company = _company(client, admin, app, fake, tmp_path, "pack-foreign@example.com")

    preview = client.post(
        _pack_url(foreign_company, "preview"),
        json={"date_from": PERIOD[0], "date_to": PERIOD[1]},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["unmapped_count"] == 0

    # У чужой фирмы набор не установлен: применение и отключение — 404.
    assert client.post(_pack_url(foreign_company, "apply")).status_code == 404
    assert client.post(_pack_url(foreign_company, "disable")).status_code == 404
