"""FA-R09.P1: дайджест Telegram на синтетическом полигоне (оракул, fake transport)."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import pytest
from app.integrations.telegram import MockTelegram
from app.security.context import set_context
from app.services.telegram_bot import ingest_update
from app.services.telegram_digest import _previous_materiality, consider_urgent
from sqlalchemy import text
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import freeze
from tests.synthetic_polygon.constants import polygon_frozen_moment
from tests.synthetic_polygon.digest_expectations import (
    assert_card_matches_oracle,
    assert_group_totals_match_oracle,
    company_card_oracle,
    group_totals_oracle,
)
from tests.synthetic_polygon.digest_harness import (
    TELEGRAM_USER,
    dispatch,
    latest_metrics,
    link_and_confirm,
    metrics_hash_stable,
    outbox_parts,
    patch_subscription,
    schedule,
    seed_polygon,
    sql_rows,
)

SCHEDULE_AT = polygon_frozen_moment()
MISSED_AT = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
FORBIDDEN_IN_TEXT = ("cash_gap", "restricted ", "fp_session")

@pytest.fixture(autouse=True)
def _guard_test_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


@pytest.fixture(autouse=True)
def _balances_import_enabled(app):
    app.state.settings.balances_import_enabled = True


def _rename_company(admin, company_id: str, name: str) -> None:
    with admin.begin() as connection:
        connection.execute(
            text("UPDATE companies SET name = :name WHERE id = :id"),
            {"name": name, "id": company_id},
        )


def _ingest(app, update: dict, at: datetime) -> None:
    session = app.state.session_factory()
    try:
        ingest_update(session, app.state.settings, update, at)
        session.commit()
    finally:
        session.close()


def test_polygon_group_digest_matches_oracle(client, admin, app, fake, tmp_path) -> None:
    freeze(app, SCHEDULE_AT)
    _tenant, company_ids = seed_polygon(client, admin, app, fake, tmp_path)
    _rename_company(admin, company_ids["retail"], "<Synth & Retail>")
    link_and_confirm(client, app, SCHEDULE_AT)
    patch_subscription(
        client,
        {"mode": "group", "privacy_level": "compact", "instant_alerts": False},
    )
    assert schedule(app, SCHEDULE_AT) == 1
    assert schedule(app, SCHEDULE_AT) == 0
    assert sql_rows(admin, "SELECT count(*) FROM digest_snapshots")[0][0] == 1

    metrics = latest_metrics(admin)
    assert metrics["report_date"] == "2026-10-31"
    assert metrics["partial"] is False
    assert_group_totals_match_oracle(metrics["totals"])
    slug_by_id = {value: key for key, value in company_ids.items()}
    for card in metrics["companies"]:
        assert_card_matches_oracle(card, slug_by_id[card["company_id"]])

    svc = next(
        card for card in metrics["companies"] if slug_by_id[card["company_id"]] == "services"
    )
    assert svc["revenue_yesterday"] == "0.00"
    assert metrics_hash_stable(metrics)

    transport = MockTelegram()
    dispatch(app, transport, SCHEDULE_AT)
    assert transport.sent
    text_value = "\n\n".join(part[0] for part in outbox_parts(admin))
    oracle = group_totals_oracle()
    assert oracle["cash_total"] in text_value
    assert oracle["revenue_mtd"] in text_value
    assert "Выручка вчера: 0.00" in text_value
    assert "ограниченные средства" in text_value
    assert "&lt;Synth &amp; Retail&gt;" in text_value
    for token in FORBIDDEN_IN_TEXT:
        assert token not in text_value
    from tests.synthetic_polygon.digest_harness import assert_parts_within_telegram_limit

    assert_parts_within_telegram_limit(admin)


def test_polygon_per_company_subscription(client, admin, app, fake, tmp_path) -> None:
    freeze(app, SCHEDULE_AT)
    _tenant, company_ids = seed_polygon(client, admin, app, fake, tmp_path)
    link_and_confirm(client, app, SCHEDULE_AT)
    patch_subscription(
        client,
        {
            "mode": "per_company",
            "privacy_level": "full",
            "company_scope": [company_ids["services"]],
        },
    )
    schedule(app, SCHEDULE_AT)
    metrics = latest_metrics(admin)
    assert metrics["mode"] == "per_company"
    assert len(metrics["companies"]) == 1
    assert metrics["totals"]["cash_total"] == company_card_oracle("services")["cash_total"]
    assert_card_matches_oracle(metrics["companies"][0], "services")


def test_polygon_partial_scope_suppresses_group_totals(
    client, admin, app, fake, tmp_path
) -> None:
    freeze(app, SCHEDULE_AT)
    tenant_id, company_ids = seed_polygon(client, admin, app, fake, tmp_path)
    unpaid_id = company_ids["subscription"]
    with admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE company_entitlements SET status = 'inactive', "
                "active_until = '2026-09-01T00:00:00+00:00' WHERE company_id = :cid"
            ),
            {"cid": unpaid_id},
        )
    link_and_confirm(client, app, SCHEDULE_AT)
    patch_subscription(
        client,
        {"mode": "group", "company_scope": list(company_ids.values())},
    )
    schedule(app, SCHEDULE_AT)
    metrics = latest_metrics(admin)
    assert metrics["partial"] is True
    assert metrics["totals"]["cash_total"] is None
    assert "partial_scope" in metrics["quality_flags"]
    text_value = outbox_parts(admin)[0][0]
    assert "неполный агрегат" in text_value
    assert group_totals_oracle()["cash_total"] not in text_value


def test_missed_slot_does_not_backfill_digest(client, admin, app, fake, tmp_path) -> None:
    freeze(app, SCHEDULE_AT)
    seed_polygon(client, admin, app, fake, tmp_path)
    link_and_confirm(client, app, SCHEDULE_AT)
    schedule(app, SCHEDULE_AT)
    assert schedule(app, MISSED_AT) == 0
    assert sql_rows(admin, "SELECT count(*) FROM digest_snapshots")[0][0] == 1
    last = sql_rows(admin, "SELECT last_scheduled_for FROM digest_subscriptions")[0][0]
    assert str(last) == "2026-11-02"


def test_quiet_hours_block_urgent(client, admin, app, fake, tmp_path) -> None:
    freeze(app, SCHEDULE_AT)
    _tenant, company_ids = seed_polygon(client, admin, app, fake, tmp_path)
    link_and_confirm(client, app, SCHEDULE_AT)
    patch_subscription(
        client,
        {"instant_alerts": True, "quiet_start": "08:00", "quiet_end": "12:00"},
    )
    session = app.state.worker_session_factory()
    try:
        created = consider_urgent(session, app.state.settings, SCHEDULE_AT)
        session.commit()
    finally:
        session.close()
    assert created == 0
    transport = MockTelegram()
    dispatch(app, transport, SCHEDULE_AT)
    urgent = sql_rows(admin, "SELECT count(*) FROM notification_outbox WHERE alert_id IS NOT NULL")
    assert urgent[0][0] == 0


def test_first_open_alert_is_not_urgent_until_prior_sent(
    client, admin, app, fake, tmp_path
) -> None:
    """Текущее поведение: срочная очередь только после materiality в уже отправленном outbox."""
    freeze(app, SCHEDULE_AT)
    seed_polygon(client, admin, app, fake, tmp_path)
    link_and_confirm(client, app, SCHEDULE_AT)
    patch_subscription(client, {"instant_alerts": True, "quiet_start": None, "quiet_end": None})
    schedule(app, SCHEDULE_AT)
    session = app.state.worker_session_factory()
    try:
        before_dispatch = consider_urgent(session, app.state.settings, SCHEDULE_AT)
        session.commit()
    finally:
        session.close()
    assert before_dispatch == 0
    dispatch(app, MockTelegram(), SCHEDULE_AT)


def test_revoked_binding_cancels_before_fake_send(client, admin, app, fake, tmp_path) -> None:
    freeze(app, SCHEDULE_AT)
    seed_polygon(client, admin, app, fake, tmp_path)
    link_and_confirm(client, app, SCHEDULE_AT)
    schedule(app, SCHEDULE_AT)
    _ingest(
        app,
        {
            "update_id": 3,
            "message": {
                "message_id": 3,
                "text": "/stop",
                "from": {"id": TELEGRAM_USER},
                "chat": {"id": TELEGRAM_USER, "type": "private"},
            },
        },
        SCHEDULE_AT,
    )
    transport = MockTelegram()
    dispatch(app, transport, SCHEDULE_AT)
    assert transport.sent == []
    assert sql_rows(admin, "SELECT status FROM notification_outbox")[0][0] == "cancelled"


def test_previous_materiality_scan_cost_on_large_outbox(
    client, admin, app, fake, tmp_path, migrated_database
) -> None:
    """Измерение: линейный проход по sent outbox tenant (не оптимизация)."""
    from tests.integration.conftest import login, open_workspace, register_and_verify

    register_and_verify(client, admin, "perf-materiality@example.com")
    login(client, "perf-materiality@example.com")
    tenant_id = open_workspace(client, "Perf Materiality")
    binding_id = uuid.uuid4()
    snapshot_id = uuid.uuid4()
    subscription_id = uuid.uuid4()
    target = str(uuid.uuid4())
    base = datetime(2026, 10, 1, tzinfo=UTC)
    with admin.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO telegram_bindings (
                  id, tenant_id, user_id, telegram_user_id, chat_id, status,
                  linked_at, revoked_at, created_at
                )
                SELECT :bid, :tid, m.user_id, 999001, 999001, 'active', :at, NULL, :at
                FROM memberships m WHERE m.tenant_id = :tid AND m.status = 'active' LIMIT 1
                """
            ),
            {"bid": binding_id, "tid": tenant_id, "at": base},
        )
        connection.execute(
            text(
                """
                INSERT INTO digest_subscriptions (
                  id, tenant_id, user_id, binding_id, company_scope, local_time, timezone,
                  days_of_week, mode, enabled, instant_alerts, quiet_start, quiet_end,
                  privacy_level, last_scheduled_for, created_at, updated_at
                )
                SELECT :sid, :tid, m.user_id, :bid, NULL, '08:30', 'Europe/Moscow',
                  '[1,2,3,4,5,6,7]'::jsonb, 'group', true, false, NULL, NULL,
                  'compact', NULL, :at, :at
                FROM memberships m WHERE m.tenant_id = :tid AND m.status = 'active' LIMIT 1
                """
            ),
            {"sid": subscription_id, "tid": tenant_id, "bid": binding_id, "at": base},
        )
        connection.execute(
            text(
                """
                INSERT INTO digest_snapshots (
                  id, tenant_id, subscription_id, kind, request_id, local_date, report_date,
                  scheduled_for, as_of, company_ids, metrics_json, quality_json, content_hash,
                  status, created_at
                ) VALUES (
                  :snap, :tid, :sub, 'scheduled', NULL, '2026-11-01', '2026-10-31',
                  :at, :at, '[]'::jsonb, '{}'::jsonb, '{}'::jsonb, 'deadbeef', 'ready', :at
                )
                """
            ),
            {"snap": snapshot_id, "tid": tenant_id, "sub": subscription_id, "at": base},
        )
        connection.execute(
            text(
                """
                INSERT INTO notification_outbox (
                  id, tenant_id, snapshot_id, alert_id, binding_id, part_number, materiality,
                  payload, status, attempts, next_attempt_at, created_at, sent_at
                )
                SELECT
                  gen_random_uuid(),
                  :tid,
                  :snap,
                  NULL,
                  :bid,
                  gs,
                  '',
                  jsonb_build_object(
                    'alert_id', CASE WHEN gs = 5000 THEN :target ELSE gen_random_uuid()::text END,
                    'materiality', '1.00'
                  ),
                  'sent',
                  1,
                  :at,
                  :at,
                  :at + (gs || ' seconds')::interval
                FROM generate_series(1, 5000) AS gs
                """
            ),
            {
                "tid": tenant_id,
                "snap": snapshot_id,
                "bid": binding_id,
                "target": target,
                "at": base,
            },
        )
    session = app.state.worker_session_factory()
    try:
        set_context(session, tenant_id=tenant_id, user_id=uuid.uuid4())
        started = time.perf_counter()
        found = _previous_materiality(session, tenant_id, target)
        elapsed = time.perf_counter() - started
    finally:
        session.close()
    assert found[0] is not None
    msg = f"_previous_materiality ~5000 sent: {elapsed:.3f}s"
    assert elapsed < 5.0, msg
    print(f"PERF_PREVIOUS_MATERIALITY_SECONDS={elapsed:.4f}")


