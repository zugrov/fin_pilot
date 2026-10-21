"""FA-R09.P3: уточняющие проверки срочного cash_gap и privacy (без правок app/)."""

from __future__ import annotations

import html
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from app.integrations.telegram import MockTelegram
from app.services.telegram_digest import _alert_text
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import freeze
from tests.integration.test_telegram_digest_polygon_p3 import (
    OFF_SLOT_AT,
    SCHEDULE_AT,
    _consider,
    _gap_setup,
    _urgent_count,
)
from tests.synthetic_polygon.digest_harness import dispatch, schedule, sql_rows
from tests.synthetic_polygon.digest_signal_oracle import (
    CASH_GAP,
    NEW_COUNTERPARTY,
    PLAN_OUT_ABOVE_WORSENING_THRESHOLD,
    PLAN_OUT_BELOW_WORSENING_THRESHOLD,
    PLAN_OUT_FOR_978750_MATERIALITY,
    PRIVACY_COUNTERPARTY_LABEL,
    URGENT_MATERIALITY_AFTER_25PCT_PLAN,
    WORSENING_PREVIOUS,
    WORSENING_TWENTY_PCT_FLOOR,
)


@pytest.fixture(autouse=True)
def _guard_test_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


@pytest.fixture(autouse=True)
def _balances_import_enabled(app):
    app.state.settings.balances_import_enabled = True


def _gap_after_sent_digest(client, admin, app, fake, tmp_path) -> str:
    freeze(app, SCHEDULE_AT)
    company_id = _gap_setup(client, admin, app, fake, tmp_path)
    schedule(app, SCHEDULE_AT)
    dispatch(app, MockTelegram(), SCHEDULE_AT)
    return company_id


def _add_plan(client, company_id: str, amount: str, due: str = "2026-11-08") -> None:
    created = client.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json={
            "direction": "out",
            "amount": amount,
            "due_date": due,
            "expected_date": due,
        },
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert created.status_code == 200, created.text


def test_cash_gap_worsening_plan_below_twenty_percent_no_urgent(
    client, admin, app, fake, tmp_path
) -> None:
    """Сигнал: cash_gap. План ниже порога +20% к {previous} → срочного нет."""
    floor_manual = (WORSENING_PREVIOUS * Decimal("1.20")).quantize(Decimal("0.01"))
    assert WORSENING_TWENTY_PCT_FLOOR == floor_manual
    company_id = _gap_after_sent_digest(client, admin, app, fake, tmp_path)
    _add_plan(client, company_id, PLAN_OUT_BELOW_WORSENING_THRESHOLD)
    at = SCHEDULE_AT + timedelta(hours=7)
    assert _consider(app, at) == 0
    assert _urgent_count(admin) == 0


def test_cash_gap_worsening_plan_above_twenty_percent_one_urgent(
    client, admin, app, fake, tmp_path
) -> None:
    """Сигнал: cash_gap. План выше порога +20% → одно срочное ухудшения."""
    company_id = _gap_after_sent_digest(client, admin, app, fake, tmp_path)
    _add_plan(client, company_id, PLAN_OUT_ABOVE_WORSENING_THRESHOLD)
    at = SCHEDULE_AT + timedelta(hours=7)
    assert _consider(app, at) == 1
    gap_id = sql_rows(
        admin,
        "SELECT id FROM alerts WHERE rule_type = 'cash_gap' ORDER BY first_seen_at DESC LIMIT 1",
    )[0][0]
    text_value = sql_rows(
        admin,
        f"SELECT payload->>'text' FROM notification_outbox WHERE alert_id = '{gap_id}'",
    )[0][0]
    assert CASH_GAP.label_ru in text_value
    assert str(WORSENING_PREVIOUS) in text_value


def test_cash_gap_worsening_978750_materiality_from_manual_oracle(
    client, admin, app, fake, tmp_path
) -> None:
    """435000 + план 543750 (=×1.25) → materiality 978750 в тексте срочного."""
    company_id = _gap_after_sent_digest(client, admin, app, fake, tmp_path)
    assert PLAN_OUT_FOR_978750_MATERIALITY == "543750.00"
    _add_plan(client, company_id, PLAN_OUT_FOR_978750_MATERIALITY, due="2026-11-06")
    at = SCHEDULE_AT + timedelta(hours=7)
    assert _consider(app, at) == 1
    gap_id = sql_rows(
        admin,
        "SELECT id FROM alerts WHERE rule_type = 'cash_gap' ORDER BY first_seen_at DESC LIMIT 1",
    )[0][0]
    text_value = sql_rows(
        admin,
        f"SELECT payload->>'text' FROM notification_outbox WHERE alert_id = '{gap_id}'",
    )[0][0]
    assert URGENT_MATERIALITY_AFTER_25PCT_PLAN in text_value
    assert "435000.00" in text_value


def test_first_instant_creates_urgent_for_each_high_severity_alert(
    client, admin, app, fake, tmp_path
) -> None:
    """gap_digest: reserve_breach + cash_gap (high) → 2 срочных за один consider."""
    freeze(app, OFF_SLOT_AT)
    _gap_setup(client, admin, app, fake, tmp_path)
    created = _consider(app, OFF_SLOT_AT)
    assert created == 2
    assert _urgent_count(admin) == 2
    types = sql_rows(
        admin,
        """
        SELECT a.rule_type FROM notification_outbox o
        JOIN alerts a ON a.id = o.alert_id
        ORDER BY a.rule_type
        """,
    )
    assert [row[0] for row in types] == ["cash_gap", "reserve_breach"]


def test_new_counterparty_privacy_compact_full_truncation_and_escape() -> None:
    """compact без контрагента; full — HTML-escape и усечение до 60 символов."""
    long_plain = "Z" * 61
    item_long = {
        "type": NEW_COUNTERPARTY.signal_type,
        "evidence": {"counterparty": long_plain, "amount": "350000.00"},
        "severity": "warning",
    }
    compact_line = _alert_text(item_long, "compact")
    full_line = _alert_text(item_long, "full")
    assert ("Z" * 61) not in compact_line
    unescaped_full = html.unescape(full_line)
    assert ("Z" * 60) in unescaped_full
    assert ("Z" * 61) not in unescaped_full

    escaped_cp = "<Privacy " + ("N" * 55)
    assert len(escaped_cp) > 60
    item_escape = {
        "type": NEW_COUNTERPARTY.signal_type,
        "evidence": {"counterparty": escaped_cp, "amount": "100000.00"},
        "severity": "warning",
    }
    full_escape = _alert_text(item_escape, "full")
    assert "<Privacy" not in full_escape
    assert "&lt;Privacy" in full_escape
    assert PRIVACY_COUNTERPARTY_LABEL not in full_escape
