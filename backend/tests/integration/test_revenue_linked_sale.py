"""P3-0: валидация linked_sale_entry_id на возвратах."""

from uuid import uuid4

from tests.integration.conftest import login, open_workspace, pay, register_and_verify


def _company(client, admin, app, fake, tmp_path, email: str) -> str:
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Linked sale")
    pay(client, app, fake, 1, "month")
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Co A", "kind": "company"},
    )
    assert created.status_code == 200, created.text
    company_id = created.json()["id"]
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return company_id


def _sale(client, company_id: str, *, external_id: str, key: str | None = None) -> dict:
    created = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-10",
            "document_number": external_id,
            "amount_ex_vat": "1000.00",
            "vat_amount": "200.00",
            "amount_inc_vat": "1200.00",
            "entry_type": "sale",
            "external_id": external_id,
        },
        headers={"Idempotency-Key": key or uuid4().hex},
    )
    assert created.status_code == 200, created.text
    return created.json()


def _return(
    client,
    company_id: str,
    *,
    linked_sale_entry_id: str | None = None,
    key: str | None = None,
) -> dict:
    body = {
        "recognition_date": "2026-10-11",
        "document_number": "RET-1",
        "amount_ex_vat": "100.00",
        "vat_amount": "20.00",
        "amount_inc_vat": "120.00",
        "entry_type": "return",
        "external_id": "ret-1",
    }
    if linked_sale_entry_id is not None:
        body["linked_sale_entry_id"] = linked_sale_entry_id
    created = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json=body,
        headers={"Idempotency-Key": key or uuid4().hex},
    )
    return created


def test_return_links_to_sale(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "link-ok@example.com")
    sale = _sale(client, company_id, external_id="s1")
    resp = _return(client, company_id, linked_sale_entry_id=sale["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["linked_sale_entry_id"] == sale["id"]


def test_linked_sale_rejects_non_sale(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "link-ret@example.com")
    first = _return(client, company_id)
    assert first.status_code == 200, first.text
    second = _return(client, company_id, linked_sale_entry_id=first.json()["id"])
    assert second.status_code == 422, second.text


def test_linked_sale_rejects_other_company(client, admin, app, fake, tmp_path) -> None:
    company_a = _company(client, admin, app, fake, tmp_path, "link-a@example.com")
    sale = _sale(client, company_a, external_id="s-a")
    company_b = _company(client, admin, app, fake, tmp_path, "link-b@example.com")
    resp = _return(client, company_b, linked_sale_entry_id=sale["id"])
    assert resp.status_code == 404, resp.text


def _patch_link(client, company_id: str, ret: dict, sale_id: str | None, *, key: str) -> dict:
    return client.patch(
        f"/api/v1/companies/{company_id}/revenue/{ret['id']}/linked-sale",
        json={"linked_sale_entry_id": sale_id, "version": ret["version"]},
        headers={"Idempotency-Key": key},
    )


def test_patch_linked_sale_rejects_self_link(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "link-self@example.com")
    ret = _return(client, company_id)
    assert ret.status_code == 200, ret.text
    patched = _patch_link(client, company_id, ret.json(), ret.json()["id"], key="link-self")
    assert patched.status_code == 422, patched.text


def test_patch_linked_sale_requires_idempotency_key(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "link-idem@example.com")
    sale = _sale(client, company_id, external_id="s-idem")
    ret = _return(client, company_id)
    assert ret.status_code == 200, ret.text
    missing = client.patch(
        f"/api/v1/companies/{company_id}/revenue/{ret.json()['id']}/linked-sale",
        json={"linked_sale_entry_id": sale["id"], "version": ret.json()["version"]},
    )
    assert missing.status_code == 400, missing.text


def test_patch_linked_sale_version_conflict(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "link-ver@example.com")
    sale = _sale(client, company_id, external_id="s-ver")
    ret = _return(client, company_id)
    assert ret.status_code == 200, ret.text
    payload = ret.json()
    first = _patch_link(client, company_id, payload, sale["id"], key="link-v1")
    assert first.status_code == 200, first.text
    stale = _patch_link(client, company_id, payload, sale["id"], key="link-v2")
    assert stale.status_code == 409, stale.text


def test_patch_linked_sale_idempotency_replay(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "link-replay@example.com")
    sale = _sale(client, company_id, external_id="s-replay")
    ret = _return(client, company_id)
    assert ret.status_code == 200, ret.text
    payload = ret.json()
    key = "link-replay-key"
    first = _patch_link(client, company_id, payload, sale["id"], key=key)
    assert first.status_code == 200, first.text
    replay = _patch_link(client, company_id, payload, sale["id"], key=key)
    assert replay.status_code == 200, replay.text
    assert replay.json()["linked_sale_entry_id"] == sale["id"]


def test_patch_linked_sale_wrong_company_returns_404(client, admin, app, fake, tmp_path) -> None:
    company_a = _company(client, admin, app, fake, tmp_path, "link-404a@example.com")
    ret = _return(client, company_a)
    assert ret.status_code == 200, ret.text
    company_b = _company(client, admin, app, fake, tmp_path, "link-404b@example.com")
    sale_b = _sale(client, company_b, external_id="s-b")
    hidden = client.patch(
        f"/api/v1/companies/{company_b}/revenue/{ret.json()['id']}/linked-sale",
        json={"linked_sale_entry_id": sale_b["id"], "version": ret.json()["version"]},
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert hidden.status_code == 404, hidden.text


def test_patch_linked_sale_rejects_void_sale(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "link-void@example.com")
    sale = _sale(client, company_id, external_id="s-void")
    ret = _return(client, company_id)
    assert ret.status_code == 200, ret.text
    voided = client.post(
        f"/api/v1/revenue/{sale['id']}/void",
        json={"version": sale["version"]},
    )
    assert voided.status_code == 200, voided.text
    patched = _patch_link(client, company_id, ret.json(), sale["id"], key="link-void")
    assert patched.status_code == 422, patched.text


def test_sale_rejects_linked_sale_field(client, admin, app, fake, tmp_path) -> None:
    company_id = _company(client, admin, app, fake, tmp_path, "link-sale@example.com")
    other = _sale(client, company_id, external_id="s-other")
    created = client.post(
        f"/api/v1/companies/{company_id}/revenue",
        json={
            "recognition_date": "2026-10-10",
            "amount_inc_vat": "100.00",
            "entry_type": "sale",
            "linked_sale_entry_id": other["id"],
        },
        headers={"Idempotency-Key": uuid4().hex},
    )
    assert created.status_code == 422, created.text
