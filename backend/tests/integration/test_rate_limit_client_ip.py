from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Receive, Scope, Send

from tests.integration.conftest import PASSWORD


class _TrustedProxyClientHost:
    def __init__(self, app: ASGIApp, host: str) -> None:
        self._app = app
        self._host = host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope = dict(scope)
            scope["client"] = (self._host, 0)
        await self._app(scope, receive, send)


def _register(client: TestClient, email: str, xff: str) -> int:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": PASSWORD, "name": "Тест"},
        headers={"X-Forwarded-For": xff},
    )
    return response.status_code


def test_register_rate_limit_is_per_client_behind_trusted_proxy(app) -> None:
    app.state.settings.trust_proxy = True
    wrapped: ASGIApp = _TrustedProxyClientHost(app, "172.18.0.2")

    with TestClient(wrapped) as client:
        client_a = "198.51.100.11"
        client_b = "198.51.100.12"
        for index in range(5):
            status = _register(client, f"rl-a-{index}@example.com", client_a)
            assert status == 200, index

        limited = _register(client, f"rl-a-extra@example.com", client_a)
        assert limited == 429

        still_ok = _register(client, f"rl-b-0@example.com", client_b)
        assert still_ok == 200


def test_spoofed_forwarded_ignored_when_peer_not_trusted(client, app) -> None:
    app.state.settings.trust_proxy = True
    app.state.settings.yookassa_ip_allowlist = "203.0.113.10"
    response = client.post(
        "/api/v1/integrations/yookassa/webhook",
        json={"event": "payment.succeeded", "object": {"id": "missing"}},
        headers={"X-Forwarded-For": "203.0.113.10"},
    )
    assert response.status_code == 403
