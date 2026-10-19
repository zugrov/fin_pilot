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
from tests.integration.test_cash import _ready


def _wallet_visible(admin, company_id: str, code: str) -> bool:
    with admin.connect() as connection:
        found = connection.execute(
            text(
                "SELECT 1 FROM wallets "
                "WHERE company_id = :company_id AND code = :code LIMIT 1"
            ),
            {"company_id": company_id, "code": code},
        ).first()
    return found is not None


def _wallet_count_for_company(admin, company_id: str) -> int:
    with admin.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM wallets WHERE company_id = :company_id"),
                {"company_id": company_id},
            ).scalar_one()
        )


def _audit_wallet_created(admin, wallet_id: str) -> int:
    with admin.connect() as connection:
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM audit_log "
                    "WHERE action = 'wallet_created' AND entity_id = :wid"
                ),
                {"wid": wallet_id},
            ).scalar_one()
        )


class _ResponseStartProbe:
    def __init__(
        self,
        app: Callable[..., Awaitable[Any]],
        *,
        on_response_start: Callable[[], None],
        match_post_wallets: bool,
    ) -> None:
        self._app = app
        self._on_response_start = on_response_start
        self._match_post_wallets = match_post_wallets

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        method = scope.get("method", "")
        path = scope.get("path", "")

        async def send_wrapper(message):
            if (
                message["type"] == "http.response.start"
                and self._match_post_wallets
                and method == "POST"
                and path.endswith("/wallets")
                and 200 <= message["status"] < 300
            ):
                self._on_response_start()
            await send(message)

        await self._app(scope, receive, send_wrapper)


def _asgi_post(
    app,
    *,
    path: str,
    json_body: dict,
    headers: dict,
    cookies: dict,
    on_response_start: Callable[[], None],
) -> httpx.Response:
    probed = _ResponseStartProbe(
        app,
        on_response_start=on_response_start,
        match_post_wallets=True,
    )

    async def _run() -> httpx.Response:
        transport = httpx.ASGITransport(app=probed)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
            return await http.post(
                path,
                json=json_body,
                headers=headers,
                cookies=cookies,
            )

    return asyncio.run(_run())


def test_wallet_create_visible_on_response_start_before_get_db_commit(
    client, admin, app, fake, migrated_database
) -> None:
    assert_finpilot_test_database(migrated_database)
    _tenant, company_id = _ready(client, admin, app, fake, "wallet-commit-probe@example.com")
    code = f"probe-{uuid4().hex[:8]}"
    key = uuid4().hex
    visible: list[bool] = []

    response = _asgi_post(
        app,
        path=f"/api/v1/companies/{company_id}/wallets",
        json_body={
            "name": "Probe",
            "type": "bank",
            "availability_type": "spendable",
            "code": code,
        },
        headers={
            "X-Tenant-Id": client.headers["X-Tenant-Id"],
            "X-CSRF-Token": client.headers["X-CSRF-Token"],
            "Idempotency-Key": key,
        },
        cookies=dict(client.cookies),
        on_response_start=lambda: visible.append(_wallet_visible(admin, company_id, code)),
    )
    assert response.status_code == 200, response.text
    assert len(visible) == 1
    assert visible[0] is True, (
        "на http.response.start кошелёк должен быть виден из независимого соединения "
        "(get_db scope=function: commit до response.start)"
    )
    body = response.json()
    assert body["code"] == code
    assert _wallet_visible(admin, company_id, code)


def test_wallet_create_immediate_independent_read_after_success(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "wallet-commit-read@example.com")
    code = f"read-{uuid4().hex[:8]}"
    key = uuid4().hex
    before = _wallet_count_for_company(admin, company_id)
    created = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={
            "name": "Read probe",
            "type": "bank",
            "availability_type": "spendable",
            "code": code,
        },
        headers={"Idempotency-Key": key},
    )
    assert created.status_code == 200, created.text
    assert _wallet_visible(admin, company_id, code)
    assert _wallet_count_for_company(admin, company_id) == before + 1


def test_wallet_create_idempotency_replay_after_early_commit(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "wallet-commit-idem@example.com")
    key = "wallet-commit-idem-key"
    first = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Idem", "type": "bank", "availability_type": "spendable", "code": "idem1"},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200, first.text
    wallet_id = first.json()["id"]
    second = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Idem", "type": "bank", "availability_type": "spendable", "code": "idem1"},
        headers={"Idempotency-Key": key},
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == wallet_id
    assert _wallet_count_for_company(admin, company_id) == 1
    assert _audit_wallet_created(admin, wallet_id) == 1


def test_wallet_create_idempotency_payload_conflict_unchanged(client, admin, app, fake) -> None:
    _tenant, company_id = _ready(client, admin, app, fake, "wallet-commit-conflict@example.com")
    key = "wallet-commit-conflict-key"
    first = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "A", "type": "bank", "availability_type": "spendable", "code": "ca"},
        headers={"Idempotency-Key": key},
    )
    assert first.status_code == 200
    clash = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "B", "type": "bank", "availability_type": "spendable", "code": "cb"},
        headers={"Idempotency-Key": key},
    )
    assert clash.status_code == 409
    assert clash.json()["code"] == "idempotency_conflict"


def test_wallet_create_commit_failure_not_success_and_rolls_back(
    client, admin, app, fake, migrated_database
) -> None:
    assert_finpilot_test_database(migrated_database)
    _tenant, company_id = _ready(client, admin, app, fake, "wallet-commit-fail@example.com")
    code = f"fail-{uuid4().hex[:8]}"
    key = uuid4().hex
    before = _wallet_count_for_company(admin, company_id)
    original_commit = Session.commit
    attempts = {"n": 0}

    def commit_side_effect(self: Session):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise SQLAlchemyError("simulated commit failure")
        return original_commit(self)

    with patch.object(Session, "commit", commit_side_effect):
        failed = client.post(
            f"/api/v1/companies/{company_id}/wallets",
            json={
                "name": "Fail",
                "type": "bank",
                "availability_type": "spendable",
                "code": code,
            },
            headers={"Idempotency-Key": key},
        )
    assert failed.status_code >= 500
    assert _wallet_count_for_company(admin, company_id) == before
    assert not _wallet_visible(admin, company_id, code)
