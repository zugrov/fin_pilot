from datetime import timedelta

from sqlalchemy import text
from tests.integration.conftest import (
    PASSWORD,
    latest_link,
    login,
    open_workspace,
    register_and_verify,
    token_from_link,
)


def test_auth1_normalized_email_is_unique(client, admin) -> None:
    first = client.post(
        "/api/v1/auth/register",
        json={"email": " A.B+tag@Example.com ", "password": PASSWORD, "name": "Анна"},
    )
    second = client.post(
        "/api/v1/auth/register",
        json={"email": "a.b+tag@example.com", "password": PASSWORD, "name": "Анна"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    with admin.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM users")).scalar_one()
    assert count == 1


def test_auth2_unverified_email_cannot_checkout(client, admin) -> None:
    client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "password": PASSWORD, "name": "Новый"},
    )
    login(client, "new@example.com")
    open_workspace(client)
    quoted = client.post("/api/v1/billing/quote", json={"companies": 1, "interval": "month"})
    assert quoted.status_code == 200
    checkout = client.post(
        "/api/v1/billing/checkout",
        json={"quote_id": quoted.json()["id"], "offer_accepted": True},
        headers={"Idempotency-Key": "auth2"},
    )
    assert checkout.status_code == 403
    assert checkout.json()["code"] == "email_not_verified"


def test_auth3_expired_and_used_tokens_are_rejected(client, admin) -> None:
    register_and_verify(client, admin, "used@example.com")
    again = client.post(
        "/api/v1/auth/verify-email",
        json={"token": token_from_link(latest_link(admin))},
    )
    assert again.status_code == 400
    client.post("/api/v1/auth/forgot-password", json={"email": "used@example.com"})
    token = token_from_link(latest_link(admin))
    with admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE verification_tokens SET expires_at = now() - interval '1 minute' "
                "WHERE token_hash IS NOT NULL AND purpose = 'reset_password' AND used_at IS NULL"
            )
        )
    expired = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "password": "another-password-2"},
    )
    assert expired.status_code == 400


def test_auth4_reset_revokes_sessions(client, admin) -> None:
    register_and_verify(client, admin, "reset@example.com")
    login(client, "reset@example.com")
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    client.post("/api/v1/auth/forgot-password", json={"email": "reset@example.com"})
    token = token_from_link(latest_link(admin))
    reset = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "password": "another-password-2"},
    )
    assert reset.status_code == 200
    old = client.get("/api/v1/auth/me")
    assert old.status_code == 401
    fresh = client.post(
        "/api/v1/auth/login",
        json={"email": "reset@example.com", "password": "another-password-2"},
    )
    assert fresh.status_code == 200


def test_auth5_forgot_does_not_reveal_account(client, admin) -> None:
    register_and_verify(client, admin, "known@example.com")
    known = client.post("/api/v1/auth/forgot-password", json={"email": "known@example.com"})
    unknown = client.post("/api/v1/auth/forgot-password", json={"email": "missing@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


def test_auth6_invited_user_joins_existing_subscription(client, admin) -> None:
    register_and_verify(client, admin, "owner@example.com")
    login(client, "owner@example.com")
    tenant_id = open_workspace(client)
    invited = client.post(
        f"/api/v1/workspaces/{tenant_id}/invitations",
        json={"email": "staff@example.com", "role": "viewer"},
    )
    assert invited.status_code == 200
    token = token_from_link(latest_link(admin))
    guest = client.__class__(client.app)
    register_and_verify(guest, admin, "staff@example.com", name="Сотрудник")
    logged = login(guest, "staff@example.com")
    accepted = guest.post("/api/v1/auth/invitations/accept", json={"token": token})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["tenant_id"] == tenant_id
    with admin.connect() as connection:
        subscriptions = connection.execute(text("SELECT count(*) FROM subscriptions")).scalar_one()
        role = connection.execute(
            text(
                "SELECT role FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE u.normalized_email = 'staff@example.com'"
            )
        ).scalar_one()
    assert subscriptions == 1
    assert role == "viewer"
    assert logged["user"]["email_verified"] is True
    _ = timedelta
