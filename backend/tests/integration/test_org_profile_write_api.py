"""P2b: API записи профиля организации."""

from __future__ import annotations

import uuid
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.integration.conftest import (
    PASSWORD,
    latest_email_link,
    login,
    open_workspace,
    register_and_verify,
    token_from_link,
)
from tests.integration.test_org_profile_api import _company_bare


def _complete_body(**overrides) -> dict:
    base = {
        "org_form": "ooo",
        "tax_system": "usn",
        "usn_tax_object": "income",
        "vat_status": "not_applicable",
        "accounting_source": "onec",
        "money_channels": ["bank"],
        "month_close_policy": "calendar_month_end",
        "revenue_recognition_method": "accrual",
        "is_new_organization": True,
        "change_reason": "тест",
    }
    base.update(overrides)
    return base


def _audit_count(admin, action: str) -> int:
    with admin.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM audit_log WHERE action = :a"),
                {"a": action},
            ).scalar_one()
        )


def _latest_version_id(client, company_id: str) -> str:
    listed = client.get(f"/api/v1/companies/{company_id}/organization-profile/versions")
    assert listed.status_code == 200, listed.text
    return listed.json()["versions"][-1]["version_id"]


def _patch_draft(client, company_id: str, **kwargs) -> dict:
    response = client.patch(
        f"/api/v1/companies/{company_id}/organization-profile/draft",
        json=_complete_body(**kwargs),
    )
    return response


def _patch_draft_json(client, company_id: str, body: dict):
    return client.patch(
        f"/api/v1/companies/{company_id}/organization-profile/draft",
        json=body,
    )


def _assert_audit_payloads_clean(admin, action: str) -> None:
    with admin.connect() as connection:
        rows = connection.execute(
            text(
                """
                SELECT before_redacted::text, after_redacted::text
                FROM audit_log WHERE action = :a
                """
            ),
            {"a": action},
        ).all()
    for before_raw, after_raw in rows:
        for raw in (before_raw, after_raw):
            if raw is None:
                continue
            lowered = raw.lower()
            assert "inn" not in lowered
            assert "email" not in lowered
            assert "password" not in lowered


def _confirm(client, company_id: str, version_id: str, *, key: str | None = None) -> dict:
    response = client.post(
        f"/api/v1/companies/{company_id}/organization-profile/versions/{version_id}/confirm",
        headers={"Idempotency-Key": key or uuid.uuid4().hex},
    )
    return response


def _post_version(client, company_id: str, effective_from: str, *, key: str | None = None) -> dict:
    body = _complete_body(effective_from=effective_from, change_reason="новая версия")
    response = client.post(
        f"/api/v1/companies/{company_id}/organization-profile/versions",
        json=body,
        headers={"Idempotency-Key": key or uuid.uuid4().hex},
    )
    return response


def test_write_requires_verified_email(client, admin) -> None:
    email = "opw-unverified@example.com"
    registered = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "name": "U"},
    )
    assert registered.status_code == 200
    login(client, email)
    tenant_id = open_workspace(client)
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Co", "kind": "company"},
    )
    assert created.status_code == 200, created.text
    company_id = created.json()["id"]
    response = _patch_draft(client, company_id)
    assert response.status_code == 403
    assert response.json()["code"] == "email_not_verified"


def test_viewer_cannot_write_profile(client, admin) -> None:
    tenant_id, company_id = _company_bare(client, admin, "opw-viewer-owner@example.com")
    invited = client.post(
        f"/api/v1/workspaces/{tenant_id}/invitations",
        json={"email": "opw-viewer@example.com", "role": "viewer"},
    )
    assert invited.status_code == 200
    token = token_from_link(latest_email_link(admin, "opw-viewer@example.com", "invite"))
    guest = TestClient(client.app)
    register_and_verify(guest, admin, "opw-viewer@example.com")
    guest_login = login(guest, "opw-viewer@example.com")
    guest.post("/api/v1/auth/invitations/accept", json={"token": token})
    client.post(
        f"/api/v1/workspaces/{tenant_id}/company-access",
        json={"user_id": guest_login["user"]["id"], "company_id": company_id},
    )
    guest.headers["X-CSRF-Token"] = guest_login["csrf_token"]
    guest.headers["X-Tenant-Id"] = tenant_id
    response = _patch_draft(guest, company_id)
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_owner_draft_confirm_and_immutable(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-flow@example.com")
    before_audit = _audit_count(admin, "organization_profile_draft_updated")
    patched = _patch_draft(client, company_id, tax_system="usn")
    assert patched.status_code == 200, patched.text
    assert _audit_count(admin, "organization_profile_draft_updated") == before_audit + 1

    version_id = patched.json()["version_id"]
    confirm_before = _audit_count(admin, "organization_profile_confirmed")
    confirmed = _confirm(client, company_id, version_id)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["is_confirmed"] is True
    assert confirm_before + 1 == _audit_count(admin, "organization_profile_confirmed")

    blocked = _patch_draft(
        client, company_id, industry_sphere="services", change_reason="поздно"
    )
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "already_confirmed"


def test_create_version_after_confirm(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-v2@example.com")
    _patch_draft(client, company_id)
    version_id = _latest_version_id(client, company_id)
    _confirm(client, company_id, version_id)

    with admin.connect() as connection:
        eff = date.fromisoformat(
            connection.execute(
                text(
                    "SELECT effective_from::text FROM organization_profile_versions "
                    "WHERE company_id = :cid ORDER BY effective_from DESC LIMIT 1"
                ),
                {"cid": company_id},
            ).scalar_one()
        )
    if eff.month == 12:
        next_eff = date(eff.year + 1, 1, 1)
    else:
        next_eff = date(eff.year, eff.month + 1, 1)
    create_before = _audit_count(admin, "organization_profile_version_created")
    created = _post_version(client, company_id, next_eff.isoformat())
    assert created.status_code == 200, created.text
    assert created.json()["effective_from"] == next_eff.isoformat()
    assert _audit_count(admin, "organization_profile_version_created") == create_before + 1


def test_draft_exists_blocks_new_version(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-draft-exists@example.com")
    blocked = _post_version(client, company_id, "2026-08-01")
    assert blocked.status_code == 400
    assert blocked.json()["code"] == "draft_exists"


def test_effective_from_not_after_latest(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-eff-date@example.com")
    _patch_draft(client, company_id)
    version_id = _latest_version_id(client, company_id)
    _confirm(client, company_id, version_id)

    with admin.connect() as connection:
        eff = connection.execute(
            text(
                "SELECT effective_from::text FROM organization_profile_versions "
                "WHERE company_id = :cid ORDER BY effective_from DESC LIMIT 1"
            ),
            {"cid": company_id},
        ).scalar_one()

    blocked = _post_version(client, company_id, eff)
    assert blocked.status_code == 400
    assert blocked.json()["code"] == "effective_from_not_after_latest"


def test_other_tenant_write_404(client, admin) -> None:
    _, company_a = _company_bare(client, admin, "opw-iso-a@example.com")
    register_and_verify(client, admin, "opw-iso-b@example.com")
    login(client, "opw-iso-b@example.com")
    open_workspace(client, "B")
    response = _patch_draft(client, company_a)
    assert response.status_code == 404


def test_confirm_idempotent(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-idem@example.com")
    _patch_draft(client, company_id)
    version_id = _latest_version_id(client, company_id)
    key = uuid.uuid4().hex
    first = _confirm(client, company_id, version_id, key=key)
    assert first.status_code == 200, first.text
    audit_after_first = _audit_count(admin, "organization_profile_confirmed")
    second = _confirm(client, company_id, version_id, key=key)
    assert second.status_code == 200, second.text
    assert second.json()["version_id"] == first.json()["version_id"]
    assert _audit_count(admin, "organization_profile_confirmed") == audit_after_first


def test_patch_partial_keeps_other_fields(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-partial@example.com")
    first = _patch_draft(client, company_id)
    assert first.status_code == 200, first.text
    assert first.json()["org_form"] == "ooo"
    assert first.json()["tax_system"] == "usn"
    second = _patch_draft_json(
        client,
        company_id,
        {"industry_sphere": "services", "change_reason": "только сфера"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["org_form"] == "ooo"
    assert second.json()["tax_system"] == "usn"
    assert second.json()["industry_sphere"] == "services"


def test_patch_unknown_field_validation_error(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-extra@example.com")
    response = _patch_draft_json(
        client,
        company_id,
        {"change_reason": "x", "extra_field": "nope"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


def test_post_without_idempotency_key(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-no-idem@example.com")
    response = client.post(
        f"/api/v1/companies/{company_id}/organization-profile/versions",
        json=_complete_body(effective_from="2099-01-01", change_reason="x"),
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"
    version_id = _latest_version_id(client, company_id)
    confirm = client.post(
        f"/api/v1/companies/{company_id}/organization-profile/versions/{version_id}/confirm",
    )
    assert confirm.status_code == 400
    assert confirm.json()["code"] == "validation_error"


def test_viewer_cannot_post_or_confirm(client, admin) -> None:
    tenant_id, company_id = _company_bare(client, admin, "opw-viewer-post@example.com")
    _patch_draft(client, company_id)
    version_id = _latest_version_id(client, company_id)
    invited = client.post(
        f"/api/v1/workspaces/{tenant_id}/invitations",
        json={"email": "opw-viewer-post-guest@example.com", "role": "viewer"},
    )
    assert invited.status_code == 200
    token = token_from_link(
        latest_email_link(admin, "opw-viewer-post-guest@example.com", "invite")
    )
    guest = TestClient(client.app)
    register_and_verify(guest, admin, "opw-viewer-post-guest@example.com")
    guest_login = login(guest, "opw-viewer-post-guest@example.com")
    guest.post("/api/v1/auth/invitations/accept", json={"token": token})
    client.post(
        f"/api/v1/workspaces/{tenant_id}/company-access",
        json={"user_id": guest_login["user"]["id"], "company_id": company_id},
    )
    guest.headers["X-CSRF-Token"] = guest_login["csrf_token"]
    guest.headers["X-Tenant-Id"] = tenant_id
    denied_confirm = _confirm(guest, company_id, version_id)
    assert denied_confirm.status_code == 403
    denied_create = _post_version(guest, company_id, "2099-02-01")
    assert denied_create.status_code == 403


def test_write_without_csrf(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-csrf@example.com")
    token = client.headers.pop("X-CSRF-Token")
    try:
        denied = _patch_draft_json(
            client, company_id, {"tax_system": "usn", "change_reason": "csrf"}
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "csrf"
    finally:
        client.headers["X-CSRF-Token"] = token


def test_invalid_profile_field_errors(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-invalid@example.com")
    response = _patch_draft_json(
        client,
        company_id,
        {"tax_system": "llc", "change_reason": "bad"},
    )
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "profile_validation_failed"
    assert "tax_system" in body["details"]["field_errors"]


def test_confirm_incomplete_lists_missing(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-incomplete@example.com")
    _patch_draft_json(client, company_id, {"tax_system": "usn", "change_reason": "мин"})
    version_id = _latest_version_id(client, company_id)
    response = _confirm(client, company_id, version_id)
    assert response.status_code == 400
    assert response.json()["code"] == "profile_confirm_incomplete"
    missing = response.json()["details"]["field_errors"]["_confirm_minimum"]
    assert "usn_tax_object" in missing


def test_version_create_idempotency_replay_and_conflict(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-idem-ver@example.com")
    _patch_draft(client, company_id)
    version_id = _latest_version_id(client, company_id)
    _confirm(client, company_id, version_id)
    with admin.connect() as connection:
        eff = date.fromisoformat(
            connection.execute(
                text(
                    "SELECT effective_from::text FROM organization_profile_versions "
                    "WHERE company_id = :cid ORDER BY effective_from DESC LIMIT 1"
                ),
                {"cid": company_id},
            ).scalar_one()
        )
    next_eff = date(eff.year + 1, 1, 1) if eff.month == 12 else date(eff.year, eff.month + 1, 1)
    key = uuid.uuid4().hex
    before = _audit_count(admin, "organization_profile_version_created")
    first = _post_version(client, company_id, next_eff.isoformat(), key=key)
    assert first.status_code == 200, first.text
    second = _post_version(client, company_id, next_eff.isoformat(), key=key)
    assert second.status_code == 200, second.text
    assert second.json()["version_id"] == first.json()["version_id"]
    assert _audit_count(admin, "organization_profile_version_created") == before + 1

    conflict = client.post(
        f"/api/v1/companies/{company_id}/organization-profile/versions",
        json=_complete_body(effective_from="2099-03-01", change_reason="другой"),
        headers={"Idempotency-Key": key},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


def test_audit_records_exclude_pii(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-audit@example.com")
    _patch_draft(client, company_id)
    version_id = _latest_version_id(client, company_id)
    _confirm(client, company_id, version_id)
    _assert_audit_payloads_clean(admin, "organization_profile_draft_updated")
    _assert_audit_payloads_clean(admin, "organization_profile_confirmed")
    _assert_audit_payloads_clean(admin, "organization_profile_version_created")


def test_accountant_can_write(client, admin) -> None:
    tenant_id, company_id = _company_bare(client, admin, "opw-acct-owner@example.com")
    invited = client.post(
        f"/api/v1/workspaces/{tenant_id}/invitations",
        json={"email": "opw-acct@example.com", "role": "accountant"},
    )
    assert invited.status_code == 200
    token = token_from_link(latest_email_link(admin, "opw-acct@example.com", "invite"))
    guest = TestClient(client.app)
    register_and_verify(guest, admin, "opw-acct@example.com")
    guest_login = login(guest, "opw-acct@example.com")
    guest.post("/api/v1/auth/invitations/accept", json={"token": token})
    client.post(
        f"/api/v1/workspaces/{tenant_id}/company-access",
        json={"user_id": guest_login["user"]["id"], "company_id": company_id},
    )
    guest.headers["X-CSRF-Token"] = guest_login["csrf_token"]
    guest.headers["X-Tenant-Id"] = tenant_id
    response = _patch_draft(guest, company_id, tax_system="usn")
    assert response.status_code == 200, response.text


def test_patch_draft_without_change_reason(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-no-reason@example.com")
    response = _patch_draft_json(client, company_id, {"tax_system": "usn"})
    assert response.status_code == 200, response.text
    assert response.json()["change_reason"] == "правка черновика"


def test_profile_mutations_include_support_and_confirm_readiness(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "opw-ready@example.com")
    read = client.get(f"/api/v1/companies/{company_id}/organization-profile")
    assert read.status_code == 200, read.text
    bootstrap = read.json()
    assert bootstrap["confirm_readiness"]["ready"] is False
    assert "org_form" in bootstrap["confirm_readiness"]["missing"]
    assert "support_level" in bootstrap
    assert "support_code" in bootstrap

    patched = _patch_draft(client, company_id)
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["confirm_readiness"]["ready"] is True
    assert body["confirm_readiness"]["missing"] == []
    assert body["support_level"] in {"supported", "partial", "unsupported"}

    version_id = body["version_id"]
    confirmed = _confirm(client, company_id, version_id)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["confirm_readiness"]["ready"] is True

    with admin.connect() as connection:
        eff = date.fromisoformat(
            connection.execute(
                text(
                    "SELECT effective_from::text FROM organization_profile_versions "
                    "WHERE company_id = :cid ORDER BY effective_from DESC LIMIT 1"
                ),
                {"cid": company_id},
            ).scalar_one()
        )
    if eff.month == 12:
        next_eff = date(eff.year + 1, 1, 1)
    else:
        next_eff = date(eff.year, eff.month + 1, 1)
    created = _post_version(client, company_id, next_eff.isoformat())
    assert created.status_code == 200, created.text
    assert created.json()["confirm_readiness"]["ready"] is True
