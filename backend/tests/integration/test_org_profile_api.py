"""P2a: чтение профиля организации через API."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text
from tests.integration.conftest import (
    freeze,
    latest_email_link,
    login,
    open_workspace,
    pay,
    register_and_verify,
    token_from_link,
)


def _company_bare(client: TestClient, admin, email: str) -> tuple[str, str]:
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Org profile API")
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Profile Co", "kind": "company", "timezone": "Europe/Moscow"},
    )
    assert created.status_code == 200, created.text
    return tenant_id, created.json()["id"]


def _company(client: TestClient, admin, app, fake, email: str) -> tuple[str, str]:
    tenant_id, company_id = _company_bare(client, admin, email)
    pay(client, app, fake, 1, "month")
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    return tenant_id, company_id


def test_organization_profile_requires_session(client, admin, app, fake) -> None:
    register_and_verify(client, admin, "op-unauth@example.com")
    login(client, "op-unauth@example.com")
    _, company_id = _company(client, admin, app, fake, "op-unauth-co@example.com")
    client.cookies.clear()
    client.headers.pop("X-CSRF-Token", None)
    client.headers.pop("X-Tenant-Id", None)
    response = client.get(f"/api/v1/companies/{company_id}/organization-profile")
    assert response.status_code == 401


def test_organization_profile_other_tenant_404(client, admin, app, fake) -> None:
    _tenant_a, company_a = _company(client, admin, app, fake, "op-tenant-a@example.com")
    register_and_verify(client, admin, "op-tenant-b@example.com")
    login(client, "op-tenant-b@example.com")
    open_workspace(client, "B")
    pay(client, app, fake, 1, "month")
    response = client.get(f"/api/v1/companies/{company_a}/organization-profile")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_viewer_can_read_profile(client, admin, app, fake) -> None:
    tenant_id, company_id = _company(client, admin, app, fake, "op-viewer-owner@example.com")
    invited = client.post(
        f"/api/v1/workspaces/{tenant_id}/invitations",
        json={"email": "op-viewer@example.com", "role": "viewer"},
    )
    assert invited.status_code == 200, invited.text
    token = token_from_link(latest_email_link(admin, "op-viewer@example.com", "invite"))
    guest = TestClient(client.app)
    register_and_verify(guest, admin, "op-viewer@example.com")
    guest_login = login(guest, "op-viewer@example.com")
    with admin.connect() as connection:
        connection.execute(
            text(
                "UPDATE users SET email_verified_at = COALESCE(email_verified_at, now()) "
                "WHERE normalized_email = :email"
            ),
            {"email": "op-viewer@example.com"},
        )
        connection.commit()
    accepted = guest.post("/api/v1/auth/invitations/accept", json={"token": token})
    assert accepted.status_code == 200, accepted.text
    granted = client.post(
        f"/api/v1/workspaces/{tenant_id}/company-access",
        json={"user_id": guest_login["user"]["id"], "company_id": company_id},
    )
    assert granted.status_code == 200, granted.text
    guest.headers["X-Tenant-Id"] = tenant_id
    response = guest.get(f"/api/v1/companies/{company_id}/organization-profile")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["company_id"] == company_id
    assert "confirmed_by" not in body


def test_period_before_first_version_is_retroactive(client, admin, app, fake) -> None:
    _, company_id = _company(client, admin, app, fake, "op-retro@example.com")
    with admin.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT id::text FROM organization_profile_versions
                WHERE company_id = :cid
                ORDER BY effective_from
                LIMIT 1
                """
            ),
            {"cid": company_id},
        ).one()
        version_id = row[0]
        connection.execute(
            text(
                """
                UPDATE organization_profile_versions
                SET effective_from = '2026-06-01', tax_system = 'usn'
                WHERE id = :vid
                """
            ),
            {"vid": version_id},
        )
        connection.commit()
    response = client.get(
        f"/api/v1/companies/{company_id}/organization-profile",
        params={"period": "2026-03-01"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["version_id"] == version_id
    assert body["tax_system"] == "usn"
    assert body["effective_from"] == "2026-06-01"


def test_unconfirmed_profile_banner(client, admin, app, fake) -> None:
    _, company_id = _company(client, admin, app, fake, "op-banner@example.com")
    response = client.get(f"/api/v1/companies/{company_id}/organization-profile")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_confirmed"] is False
    assert body["profile_unconfirmed"] is True
    assert body["confirmed_at"] is None
    assert body["confirmed_role"] is None


def test_invalid_period_not_first_of_month(client, admin, app, fake) -> None:
    _, company_id = _company(client, admin, app, fake, "op-bad-period@example.com")
    response = client.get(
        f"/api/v1/companies/{company_id}/organization-profile",
        params={"period": "2026-03-15"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "validation_error"


def test_organization_profile_readable_without_billing(client, admin) -> None:
    _, company_id = _company_bare(client, admin, "op-no-billing@example.com")
    response = client.get(f"/api/v1/companies/{company_id}/organization-profile")
    assert response.status_code == 200, response.text
    assert response.json()["company_id"] == company_id


def test_tenant_member_without_company_access_404(client, admin, app, fake) -> None:
    tenant_id, company_id = _company_bare(client, admin, "op-no-access-owner@example.com")
    invited = client.post(
        f"/api/v1/workspaces/{tenant_id}/invitations",
        json={"email": "op-no-access@example.com", "role": "viewer"},
    )
    assert invited.status_code == 200, invited.text
    token = token_from_link(latest_email_link(admin, "op-no-access@example.com", "invite"))
    guest = TestClient(client.app)
    register_and_verify(guest, admin, "op-no-access@example.com")
    login(guest, "op-no-access@example.com")
    accepted = guest.post("/api/v1/auth/invitations/accept", json={"token": token})
    assert accepted.status_code == 200, accepted.text
    guest.headers["X-Tenant-Id"] = tenant_id
    response = guest.get(f"/api/v1/companies/{company_id}/organization-profile")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_confirmed_profile_reflects_confirmation(client, admin, app, fake) -> None:
    _, company_id = _company_bare(client, admin, "op-confirmed@example.com")
    with admin.connect() as connection:
        owner_id = connection.execute(
            text(
                """
                SELECT u.id::text FROM users u
                JOIN memberships m ON m.user_id = u.id
                JOIN companies c ON c.tenant_id = m.tenant_id
                WHERE c.id = :cid AND m.role = 'owner'
                LIMIT 1
                """
            ),
            {"cid": company_id},
        ).scalar_one()
        connection.execute(
            text(
                """
                UPDATE organization_profile_versions
                SET confirmed_at = now(), confirmed_by = :uid, confirmed_role = 'owner'
                WHERE company_id = :cid
                """
            ),
            {"cid": company_id, "uid": owner_id},
        )
        connection.commit()
    response = client.get(f"/api/v1/companies/{company_id}/organization-profile")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["is_confirmed"] is True
    assert body["profile_unconfirmed"] is False
    assert body["confirmed_role"] == "owner"
    assert body["confirmed_at"] is not None


def test_tenant_isolation_versions_list(client, admin, app, fake) -> None:
    tenant_a, company_a = _company(client, admin, app, fake, "op-iso-a@example.com")
    register_and_verify(client, admin, "op-iso-b@example.com")
    login(client, "op-iso-b@example.com")
    tenant_b = open_workspace(client, "Iso B")
    pay(client, app, fake, 1, "month")
    created_b = client.post(
        f"/api/v1/workspaces/{tenant_b}/companies",
        json={"name": "B Co", "kind": "company"},
    )
    assert created_b.status_code == 200, created_b.text
    company_b = created_b.json()["id"]
    client.post(f"/api/v1/billing/companies/{company_b}/activate")

    login(client, "op-iso-a@example.com")
    client.headers["X-Tenant-Id"] = tenant_a
    list_a = client.get(f"/api/v1/companies/{company_a}/organization-profile/versions")
    assert list_a.status_code == 200, list_a.text
    assert list_a.json()["company_id"] == company_a
    assert len(list_a.json()["versions"]) >= 1
    for item in list_a.json()["versions"]:
        assert "org_form" not in item
        assert "confirmed_by" not in item

    cross = client.get(f"/api/v1/companies/{company_b}/organization-profile/versions")
    assert cross.status_code == 404


def test_default_period_uses_company_timezone(client, admin, app, fake) -> None:
    freeze(app, datetime(2026, 7, 15, 12, 0, tzinfo=UTC))
    _, company_id = _company(client, admin, app, fake, "op-tz@example.com")
    response = client.get(f"/api/v1/companies/{company_id}/organization-profile")
    assert response.status_code == 200, response.text
    assert response.json()["period"] == "2026-07-01"
