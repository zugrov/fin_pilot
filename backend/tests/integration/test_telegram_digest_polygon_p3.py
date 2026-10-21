"""FA-R09.P3: первый срочный high/critical, privacy full, cash_gap на gap_digest."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

import pytest
from app.integrations.telegram import MockTelegram
from app.services.telegram_digest import _alert_text, consider_urgent
from sqlalchemy import text
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import freeze
from tests.synthetic_polygon.constants import polygon_frozen_moment
from tests.synthetic_polygon.digest_harness import (
    dispatch,
    link_and_confirm,
    patch_subscription,
    schedule,
    seed_gap_company,
    sql_rows,
)
from tests.synthetic_polygon.digest_signal_oracle import (
    CASH_GAP,
    NEW_COUNTERPARTY,
    PRIVACY_COUNTERPARTY_LABEL,
)

SCHEDULE_AT = polygon_frozen_moment()
# Вне слота дайджеста (08:30 MSK): только consider_urgent, без плановой очереди.
OFF_SLOT_AT = datetime.fromisoformat("2026-11-01T05:00:00+00:00")


@pytest.fixture(autouse=True)
def _guard_test_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


@pytest.fixture(autouse=True)
def _balances_import_enabled(app):
    app.state.settings.balances_import_enabled = True


def _gap_setup(client, admin, app, fake, tmp_path):
    _tenant, company_id = seed_gap_company(client, admin, app, fake, tmp_path)
    link_and_confirm(client, app, OFF_SLOT_AT)
    patch_subscription(
        client,
        {
            "mode": "per_company",
            "company_scope": [company_id],
            "instant_alerts": True,
            "quiet_start": None,
            "quiet_end": None,
        },
    )
    preview = client.post("/api/v1/telegram/digest-preview")
    assert preview.status_code == 200, preview.text
    return company_id


def _consider(app, at: datetime) -> int:
    session = app.state.worker_session_factory()
    try:
        created = consider_urgent(session, app.state.settings, at)
        session.commit()
        return created
    finally:
        session.close()


def _urgent_count(admin) -> int:
    query = "SELECT count(*) FROM notification_outbox WHERE alert_id IS NOT NULL"
    return sql_rows(admin, query)[0][0]


def test_first_cash_gap_high_severity_sends_one_urgent(client, admin, app, fake, tmp_path) -> None:
    """Сигнал: cash_gap (high). Первый срочный без планового дайджеста в очереди."""
    freeze(app, OFF_SLOT_AT)
    _gap_setup(client, admin, app, fake, tmp_path)
    gap_alert_id = sql_rows(
        admin,
        "SELECT id FROM alerts WHERE rule_type = 'cash_gap' ORDER BY first_seen_at DESC LIMIT 1",
    )[0][0]
    assert _consider(app, OFF_SLOT_AT) >= 1
    gap_urgent = sql_rows(
        admin,
        f"SELECT count(*) FROM notification_outbox WHERE alert_id = '{gap_alert_id}'",
    )[0][0]
    assert gap_urgent == 1
    text_query = (
        f"SELECT payload->>'text' FROM notification_outbox WHERE alert_id = '{gap_alert_id}'"
    )
    text_value = sql_rows(admin, text_query)[0][0]
    assert CASH_GAP.label_ru in text_value
    assert CASH_GAP.gap_amount in text_value
    assert CASH_GAP.signal_type not in text_value
    assert _consider(app, OFF_SLOT_AT + timedelta(minutes=5)) == 0


def test_urgent_not_created_when_signal_in_scheduled_digest_queue(
    client, admin, app, fake, tmp_path
) -> None:
    """Сигнал: cash_gap. Плановый дайджест в outbox pending блокирует срочное."""
    freeze(app, SCHEDULE_AT)
    _gap_setup(client, admin, app, fake, tmp_path)
    schedule(app, SCHEDULE_AT)
    pending_query = (
        "SELECT count(*) FROM notification_outbox "
        "WHERE snapshot_id IS NOT NULL AND status = 'pending'"
    )
    pending_digest = sql_rows(admin, pending_query)[0][0]
    assert pending_digest >= 1
    assert _consider(app, SCHEDULE_AT) == 0
    assert _urgent_count(admin) == 0


def test_first_cash_gap_quiet_hours_zero(client, admin, app, fake, tmp_path) -> None:
    """Сигнал: cash_gap."""
    freeze(app, SCHEDULE_AT)
    _gap_setup(client, admin, app, fake, tmp_path)
    patch_subscription(client, {"quiet_start": "08:00", "quiet_end": "12:00"})
    assert _consider(app, SCHEDULE_AT) == 0
    assert _urgent_count(admin) == 0


def test_urgent_daily_limit_five_blocks_sixth(client, admin, app, fake, tmp_path) -> None:
    """Сигнал: cash_gap. Лимит 5 срочных на подписку за локальные сутки."""
    freeze(app, OFF_SLOT_AT)
    _gap_setup(client, admin, app, fake, tmp_path)
    binding_id = sql_rows(admin, "SELECT id FROM telegram_bindings LIMIT 1")[0][0]
    tenant_id = sql_rows(admin, "SELECT tenant_id FROM telegram_bindings LIMIT 1")[0][0]
    company_id = sql_rows(admin, "SELECT id FROM companies LIMIT 1")[0][0]
    at = OFF_SLOT_AT
    with admin.begin() as connection:
        for idx in range(5):
            aid = uuid.uuid4()
            connection.execute(
                text(
                    """
                    INSERT INTO alerts (
                      id, tenant_id, company_id, rule_type, fingerprint, severity, status,
                      first_seen_at, last_seen_at, evidence_json, source_refs
                    ) VALUES (
                      :aid, :tid, :cid, 'cash_gap', :fp, 'high', 'open',
                      :at, :at, '{}'::jsonb, '[]'::jsonb
                    )
                    """
                ),
                {
                    "aid": aid,
                    "tid": tenant_id,
                    "cid": company_id,
                    "fp": f"limit-test-{idx}",
                    "at": at,
                },
            )
            payload = json.dumps(
                {"text": "x", "company_ids": [str(company_id)]},
                ensure_ascii=False,
            )
            connection.execute(
                text(
                    """
                    INSERT INTO notification_outbox (
                      id, tenant_id, snapshot_id, alert_id, binding_id, part_number, materiality,
                      payload, status, attempts, next_attempt_at, created_at, sent_at
                    ) VALUES (
                      :id, :tid, NULL, :aid, :bid, 1, :mat,
                      CAST(:payload AS jsonb),
                      'sent', 0, :at, :at, :at
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "aid": aid,
                    "bid": binding_id,
                    "mat": f"{idx}.00",
                    "payload": payload,
                    "at": at,
                },
            )
    assert _consider(app, at) == 0


def test_privacy_compact_hides_counterparty_full_shows(client, admin, app, fake, tmp_path) -> None:
    """Сигнал: new_counterparty — evidence полигона; контрагент только в full."""
    freeze(app, SCHEDULE_AT)
    company_id = seed_gap_company(client, admin, app, fake, tmp_path)[1]
    link_and_confirm(client, app, SCHEDULE_AT)
    preview = client.post("/api/v1/telegram/digest-preview")
    assert preview.status_code == 200, preview.text
    evidence_row = sql_rows(
        admin,
        f"SELECT evidence_json FROM alerts WHERE company_id = '{company_id}' "
        "AND rule_type = 'new_counterparty' LIMIT 1",
    )[0][0]
    item = {
        "type": NEW_COUNTERPARTY.signal_type,
        "evidence": evidence_row,
        "severity": "warning",
    }
    compact_line = _alert_text(item, "compact")
    full_line = _alert_text(item, "full")
    assert PRIVACY_COUNTERPARTY_LABEL not in compact_line
    assert PRIVACY_COUNTERPARTY_LABEL in full_line
    assert NEW_COUNTERPARTY.label_ru in full_line


def test_revoked_membership_cancels_urgent_before_send(client, admin, app, fake, tmp_path) -> None:
    """Сигнал: cash_gap. Отзыв membership после постановки срочного в очередь."""
    freeze(app, OFF_SLOT_AT)
    _gap_setup(client, admin, app, fake, tmp_path)
    gap_alert_id = sql_rows(
        admin,
        "SELECT id FROM alerts WHERE rule_type = 'cash_gap' ORDER BY first_seen_at DESC LIMIT 1",
    )[0][0]
    assert _consider(app, OFF_SLOT_AT) >= 1
    assert (
        sql_rows(
            admin,
            f"SELECT count(*) FROM notification_outbox WHERE alert_id = '{gap_alert_id}'",
        )[0][0]
        == 1
    )
    with admin.begin() as connection:
        connection.execute(
            text(
                "DELETE FROM notification_outbox WHERE alert_id IS NOT NULL "
                "AND alert_id <> :aid"
            ),
            {"aid": gap_alert_id},
        )
        connection.execute(
            text(
                "UPDATE memberships SET status = 'inactive' "
                "WHERE user_id = (SELECT user_id FROM digest_subscriptions LIMIT 1)"
            )
        )
    transport = MockTelegram()
    dispatch(app, transport, OFF_SLOT_AT)
    assert transport.sent == []
    status_query = f"SELECT status FROM notification_outbox WHERE alert_id = '{gap_alert_id}'"
    assert sql_rows(admin, status_query)[0][0] == "cancelled"
