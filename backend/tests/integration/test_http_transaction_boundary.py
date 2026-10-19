"""HTTP transaction boundary: commit до response.start (get_db scope=function)."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import httpx
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import login, open_workspace, pay, register_and_verify
from tests.integration.test_balances_import import BAL_HEADER, _balances_source, _opening_count
from tests.integration.test_balances_import import _ready as balances_ready
from tests.integration.test_cash import _anchor, _ready, _wallet


class _ResponseStartProbe:
    def __init__(
        self,
        app: Callable[..., Awaitable[Any]],
        *,
        on_response_start: Callable[[], None],
        matcher: Callable[[str, str, int], bool],
    ) -> None:
        self._app = app
        self._on_response_start = on_response_start
        self._matcher = matcher

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        method = scope.get("method", "")
        path = scope.get("path", "")

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status = message.get("status", 0)
                if self._matcher(method, path, status):
                    self._on_response_start()
            await send(message)

        await self._app(scope, receive, send_wrapper)


def _asgi_request(
    app,
    *,
    method: str,
    path: str,
    on_response_start: Callable[[], None],
    matcher: Callable[[str, str, int], bool],
    json_body: dict | None = None,
    headers: dict | None = None,
    cookies: dict | None = None,
) -> httpx.Response:
    probed = _ResponseStartProbe(app, on_response_start=on_response_start, matcher=matcher)

    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=probed)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            kwargs: dict = {"headers": headers or {}, "cookies": cookies or {}}
            if json_body is not None:
                kwargs["json"] = json_body
            return await http.request(method, path, **kwargs)

    return asyncio.run(_run())


def _match_path(suffix: str):
    def matcher(method: str, path: str, status: int) -> bool:
        return method == "POST" and path.endswith(suffix) and 200 <= status < 300

    return matcher


def _scalar(admin, sql: str, **params):
    with admin.connect() as connection:
        return connection.execute(text(sql), params).scalar_one()


def test_one_session_per_http_request(client, app, admin, fake) -> None:
    register_and_verify(client, admin, "one-session@example.com")
    login(client, "one-session@example.com")
    created: list[Session] = []
    original = app.state.session_factory

    def tracking_factory():
        session = original()
        created.append(session)
        return session

    app.state.session_factory = tracking_factory
    try:
        client.get("/api/v1/auth/me")
    finally:
        app.state.session_factory = original
    assert len(created) == 1


def test_opening_balance_visible_on_response_start(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "opening-probe@example.com")
    wallet = _wallet(client, company_id, code="open-probe")
    key = uuid4().hex
    visible: list[bool] = []

    response = _asgi_request(
        app,
        method="POST",
        path=f"/api/v1/wallets/{wallet['id']}/opening-balance",
        json_body={"effective_at": "2026-10-01T00:00:00+00:00", "amount": "10.00"},
        headers={
            "X-Tenant-Id": client.headers["X-Tenant-Id"],
            "X-CSRF-Token": client.headers["X-CSRF-Token"],
            "Idempotency-Key": key,
        },
        cookies=dict(client.cookies),
        on_response_start=lambda: visible.append(
            int(
                _scalar(
                    admin,
                    "SELECT count(*) FROM opening_balances WHERE wallet_id = :wid",
                    wid=wallet["id"],
                )
            )
            > 0
        ),
        matcher=_match_path("/opening-balance"),
    )
    assert response.status_code == 200, response.text
    assert visible == [True]


def test_transaction_create_visible_on_response_start(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "tx-probe@example.com")
    wallet = _wallet(client, company_id)
    _anchor(client, wallet["id"])
    key = uuid4().hex
    visible: list[bool] = []

    response = _asgi_request(
        app,
        method="POST",
        path=f"/api/v1/companies/{company_id}/transactions",
        json_body={
            "wallet_id": wallet["id"],
            "business_date": "2026-10-11",
            "occurred_at": "2026-10-11T12:00:00+00:00",
            "direction": "in",
            "amount": "50.00",
            "description": "probe",
            "status": "posted",
        },
        headers={
            "X-Tenant-Id": client.headers["X-Tenant-Id"],
            "X-CSRF-Token": client.headers["X-CSRF-Token"],
            "Idempotency-Key": key,
        },
        cookies=dict(client.cookies),
        on_response_start=lambda: visible.append(
            int(
                _scalar(
                    admin,
                    "SELECT count(*) FROM idempotency_records WHERE idempotency_key = :k",
                    k=key,
                )
            )
            > 0
        ),
        matcher=_match_path("/transactions"),
    )
    assert response.status_code == 200, response.text
    assert visible == [True]


def test_revenue_create_visible_on_response_start(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "rev-probe@example.com")
    key = uuid4().hex
    visible: list[bool] = []

    response = _asgi_request(
        app,
        method="POST",
        path=f"/api/v1/companies/{company_id}/revenue",
        json_body={
            "recognition_date": "2026-10-12",
            "amount_ex_vat": "100.00",
            "vat_amount": "20.00",
            "amount_inc_vat": "120.00",
            "entry_type": "sale",
            "vat_basis": "net",
        },
        headers={
            "X-Tenant-Id": client.headers["X-Tenant-Id"],
            "X-CSRF-Token": client.headers["X-CSRF-Token"],
            "Idempotency-Key": key,
        },
        cookies=dict(client.cookies),
        on_response_start=lambda: visible.append(
            int(
                _scalar(
                    admin,
                    "SELECT count(*) FROM idempotency_records WHERE idempotency_key = :k",
                    k=key,
                )
            )
            > 0
        ),
        matcher=_match_path("/revenue"),
    )
    assert response.status_code == 200, response.text
    assert visible == [True]


def test_yookassa_webhook_inbox_visible_on_response_start(client, admin, app, fake) -> None:
    register_and_verify(client, admin, "wh-probe@example.com")
    login(client, "wh-probe@example.com")
    open_workspace(client, "WH")
    pay(client, app, fake, 1, "month")
    provider_id = next(reversed(fake.by_id))
    payload = {"event": "payment.succeeded", "object": {"id": provider_id}}
    visible: list[bool] = []

    response = _asgi_request(
        app,
        method="POST",
        path="/api/v1/integrations/yookassa/webhook",
        json_body=payload,
        on_response_start=lambda: visible.append(
            int(
                _scalar(
                    admin,
                    "SELECT count(*) FROM billing_webhook_inbox WHERE object_id = :oid",
                    oid=provider_id,
                )
            )
            > 0
        ),
        matcher=lambda method, path, status: (
            method == "POST" and path.endswith("/yookassa/webhook") and 200 <= status < 300
        ),
    )
    assert response.status_code == 200, response.text
    assert visible == [True]


def test_balances_import_commit_visible_on_response_start(
    client, admin, app, fake, migrated_database, tmp_path
) -> None:
    assert_finpilot_test_database(migrated_database)
    app.state.settings.balances_import_enabled = True
    company_id, _wallet_id = balances_ready(
        client, admin, app, fake, tmp_path, "balances-commit-probe@example.com"
    )
    source = _balances_source(client, company_id)
    upload_key = uuid4().hex
    csv_body = BAL_HEADER.encode() + b"main,2026-10-01,1000.00,RUB\n"
    uploaded = client.post(
        f"/api/v1/companies/{company_id}/imports",
        data={"connection_id": source["id"]},
        files={"upload": ("balances.csv", csv_body, "text/csv")},
        headers={"Idempotency-Key": upload_key},
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    batch_id = body["id"]
    token = body["preview_token"]
    visible: list[bool] = []

    response = _asgi_request(
        app,
        method="POST",
        path=f"/api/v1/imports/{batch_id}/commit",
        on_response_start=lambda: visible.append(_opening_count(admin, _wallet_id) > 0),
        matcher=_match_path("/commit"),
        headers={
            "X-Tenant-Id": client.headers["X-Tenant-Id"],
            "X-CSRF-Token": client.headers["X-CSRF-Token"],
            "Preview-Token": token or "",
        },
        cookies=dict(client.cookies),
    )
    assert response.status_code == 200, response.text
    assert visible == [True]


def test_auth_me_last_seen_updated_before_response_start(client, admin, app) -> None:
    register_and_verify(client, admin, "lastseen@example.com")
    login(client, "lastseen@example.com")
    before = _scalar(
        admin,
        "SELECT last_seen_at FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE u.normalized_email = :email ORDER BY s.created_at DESC LIMIT 1",
        email="lastseen@example.com",
    )
    seen: list[Any] = []

    response = _asgi_request(
        app,
        method="GET",
        path="/api/v1/auth/me",
        cookies=dict(client.cookies),
        on_response_start=lambda: seen.append(
            _scalar(
                admin,
                "SELECT last_seen_at FROM sessions s JOIN users u ON u.id = s.user_id "
                "WHERE u.normalized_email = :email ORDER BY s.created_at DESC LIMIT 1",
                email="lastseen@example.com",
            )
        ),
        matcher=lambda method, path, status: (
            method == "GET" and path.endswith("/auth/me") and 200 <= status < 300
        ),
    )
    assert response.status_code == 200
    assert seen[0] is not None
    assert seen[0] >= before


def test_commit_failure_returns_error_not_success(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "commit-fail-tx@example.com")
    wallet = _wallet(client, company_id)
    _anchor(client, wallet["id"])
    original_commit = Session.commit
    calls = {"n": 0}
    statuses: list[int] = []

    def fail_once(self: Session):
        calls["n"] += 1
        if calls["n"] == 1:
            raise SQLAlchemyError("simulated commit failure")
        return original_commit(self)

    def capture_status(method: str, path: str, status: int) -> bool:
        if method == "POST" and path.endswith("/transactions"):
            statuses.append(status)
        return False

    from fastapi.testclient import TestClient

    with patch.object(Session, "commit", fail_once):
        with TestClient(app, raise_server_exceptions=False) as http:
            http.headers.update(client.headers)
            http.cookies.update(client.cookies)
            response = http.post(
                f"/api/v1/companies/{company_id}/transactions",
                json={
                    "wallet_id": wallet["id"],
                    "business_date": "2026-10-15",
                    "occurred_at": "2026-10-15T12:00:00+00:00",
                    "direction": "in",
                    "amount": "1.00",
                    "description": "fail",
                    "status": "posted",
                },
                headers={"Idempotency-Key": uuid4().hex},
            )
    assert response.status_code >= 500


def test_yookassa_webhook_integrity_error_without_duplicate_is_not_ok(
    app, monkeypatch
) -> None:
    from app.api.v1 import webhooks as wh_mod
    from fastapi.testclient import TestClient
    from sqlalchemy.exc import IntegrityError

    payload = {"event": "payment.succeeded", "object": {"id": "prov-fail-1"}}

    def boom(*_a, **_k):
        raise IntegrityError("insert", {}, Exception("uniq"))

    monkeypatch.setattr(wh_mod, "save_webhook", boom)
    monkeypatch.setattr(wh_mod, "_webhook_already_inbox", lambda *a, **k: False)
    with TestClient(app, raise_server_exceptions=False) as http:
        response = http.post("/api/v1/integrations/yookassa/webhook", json=payload)
    assert response.status_code >= 500
