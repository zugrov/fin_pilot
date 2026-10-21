"""Harness Telegram-дайджеста на синтетическом полигоне (fake transport, реальная БД)."""

from __future__ import annotations

import html
from datetime import datetime

from app.domain.telegram_text import content_hash
from app.integrations.telegram import MockTelegram
from app.services.telegram_bot import ingest_update
from app.services.telegram_digest import render_parts, schedule_digests
from app.services.telegram_dispatch import dispatch_outbox
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine
from tests.integration.conftest import login, open_workspace, pay, register_and_verify
from tests.integration.test_synthetic_polygon import _workspace_three_companies
from tests.synthetic_polygon.constants import polygon_frozen_moment
from tests.synthetic_polygon.harness import load_profile
from tests.synthetic_polygon.profiles import ALL_PROFILES, GAP_DIGEST

TELEGRAM_USER = 901


def load_polygon_workspace(
    client: TestClient, admin: Engine, app, fake, tmp_path
) -> tuple[str, dict[str, str]]:
    app.state.settings.import_storage_dir = str(tmp_path)
    return _workspace_three_companies(client, admin, app, fake, tmp_path)


def seed_polygon(
    client: TestClient, admin: Engine, app, fake, tmp_path
) -> tuple[str, dict[str, str]]:
    tenant_id, company_ids = load_polygon_workspace(client, admin, app, fake, tmp_path)
    for profile in ALL_PROFILES:
        load_profile(client, company_ids[profile.slug], profile, admin=admin)
    return tenant_id, company_ids


def link_and_confirm(client: TestClient, app, at: datetime | None = None) -> None:
    moment = at or polygon_frozen_moment()
    token = client.post("/api/v1/telegram/link-token")
    assert token.status_code == 200, token.text
    update = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "text": f"/start {token.json()['token']}",
            "from": {"id": TELEGRAM_USER},
            "chat": {"id": TELEGRAM_USER, "type": "private"},
        },
    }
    session = app.state.session_factory()
    try:
        ingest_update(session, app.state.settings, update, moment)
        session.commit()
    finally:
        session.close()
    confirmed = client.post("/api/v1/telegram/binding/confirm")
    assert confirmed.status_code == 200, confirmed.text


def patch_subscription(client: TestClient, payload: dict) -> None:
    updated = client.put("/api/v1/telegram/subscription", json=payload)
    assert updated.status_code == 200, updated.text


def schedule(app, at: datetime) -> int:
    session = app.state.worker_session_factory()
    try:
        created = schedule_digests(session, app.state.settings, at)
        session.commit()
        return created
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispatch(app, transport: MockTelegram, at: datetime) -> int:
    session = app.state.worker_session_factory()
    try:
        handled = dispatch_outbox(session, app.state.settings, transport, at)
        session.commit()
        return handled
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def sql_rows(admin: Engine, query: str) -> list:
    with admin.connect() as connection:
        return list(connection.execute(text(query)).all())


def latest_metrics(admin: Engine) -> dict:
    row = sql_rows(
        admin,
        "SELECT metrics_json, content_hash FROM digest_snapshots ORDER BY created_at DESC LIMIT 1",
    )[0]
    metrics = row[0]
    assert isinstance(metrics, dict)
    return metrics


def outbox_parts(admin: Engine) -> list[tuple[str, str]]:
    return sql_rows(
        admin,
        "SELECT payload->>'text', payload->>'content_hash' "
        "FROM notification_outbox ORDER BY part_number",
    )


def metrics_hash_stable(metrics: dict) -> bool:
    first = content_hash(metrics)
    render_parts(metrics, "https://example.test")
    return content_hash(metrics) == first


def seed_gap_company(
    client: TestClient, admin: Engine, app, fake, tmp_path
) -> tuple[str, str]:
    app.state.settings.balances_import_enabled = True
    app.state.settings.import_storage_dir = str(tmp_path)
    register_and_verify(client, admin, "gap-digest@example.com", name="Gap Digest")
    login(client, "gap-digest@example.com")
    tenant_id = open_workspace(client, "Gap Digest WS")
    pay(client, app, fake, 1, "month")
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": GAP_DIGEST.display_name, "kind": "company", "timezone": "Europe/Moscow"},
    )
    assert created.status_code == 200, created.text
    company_id = created.json()["id"]
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    load_profile(client, company_id, GAP_DIGEST, admin=admin)
    return tenant_id, company_id


def telegram_visible_length(text: str) -> int:
    return len(html.unescape(text))


def assert_parts_within_telegram_limit(admin: Engine, *, limit: int = 4096) -> None:
    for part_text, _ in outbox_parts(admin):
        assert telegram_visible_length(part_text) <= limit
