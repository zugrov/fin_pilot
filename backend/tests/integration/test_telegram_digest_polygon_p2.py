"""FA-R09.P2: честные проверки сигналов и выручки дайджеста на полигоне."""

from __future__ import annotations

import html
import uuid
from datetime import datetime, timedelta

import pytest
from app.domain.telegram_text import signal_type_label
from app.integrations.telegram import MockTelegram
from app.services.telegram_digest import _alert_text, consider_urgent
from sqlalchemy import text
from tests.integration.balances_test_util import assert_finpilot_test_database
from tests.integration.conftest import freeze
from tests.synthetic_polygon.constants import polygon_frozen_moment
from tests.synthetic_polygon.digest_expectations import (
    DIGEST_REPORT_DATE,
    company_card_oracle,
    group_totals_oracle,
    revenue_yesterday_oracle,
)
from tests.synthetic_polygon.digest_harness import (
    assert_parts_within_telegram_limit,
    dispatch,
    latest_metrics,
    link_and_confirm,
    outbox_parts,
    patch_subscription,
    schedule,
    seed_gap_company,
    seed_polygon,
    sql_rows,
)
from tests.synthetic_polygon.digest_signal_oracle import (
    CASH_GAP,
    NEW_COUNTERPARTY,
    PRIVACY_COUNTERPARTY_LABEL,
    expected_digest_signal_types,
)
from tests.synthetic_polygon.profiles import SERVICES

SCHEDULE_AT = polygon_frozen_moment()


def _urgent_count(admin) -> int:
    query = "SELECT count(*) FROM notification_outbox WHERE alert_id IS NOT NULL"
    return sql_rows(admin, query)[0][0]


def _consider(app, at: datetime) -> int:
    session = app.state.worker_session_factory()
    try:
        created = consider_urgent(session, app.state.settings, at)
        session.commit()
        return created
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _guard_test_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


@pytest.fixture(autouse=True)
def _balances_import_enabled(app):
    app.state.settings.balances_import_enabled = True


def test_revenue_yesterday_with_coverage_is_zero(client, admin, app, fake, tmp_path) -> None:
    freeze(app, SCHEDULE_AT)
    _tenant, company_ids = seed_polygon(client, admin, app, fake, tmp_path)
    link_and_confirm(client, app, SCHEDULE_AT)
    schedule(app, SCHEDULE_AT)
    metrics = latest_metrics(admin)
    expected = revenue_yesterday_oracle(
        SERVICES,
        coverage_through=DIGEST_REPORT_DATE,
    )
    assert expected == "0.00"
    services_id = company_ids["services"]
    card = next(item for item in metrics["companies"] if item["company_id"] == services_id)
    assert card["revenue_yesterday"] == "0.00"
    text_value = outbox_parts(admin)[0][0]
    assert "Выручка вчера: 0.00" in text_value
    assert "Выручка вчера: нет данных" not in text_value


def test_revenue_yesterday_without_coverage_is_unavailable(
    client, admin, app, fake, tmp_path
) -> None:
    freeze(app, SCHEDULE_AT)
    _tenant, company_ids = seed_polygon(client, admin, app, fake, tmp_path)
    services_id = company_ids["services"]
    with admin.connect() as connection:
        source_id = connection.execute(
            text(
                "SELECT id FROM source_connections "
                "WHERE company_id = :cid AND dataset = 'revenue' LIMIT 1"
            ),
            {"cid": services_id},
        ).scalar_one()
    cleared = client.post(
        f"/api/v1/companies/{services_id}/sources/{source_id}/coverage",
        json={"coverage_through": "2026-10-01"},
    )
    assert cleared.status_code == 200, cleared.text
    link_and_confirm(client, app, SCHEDULE_AT)
    patch_subscription(client, {"mode": "per_company", "company_scope": [services_id]})
    schedule(app, SCHEDULE_AT)
    metrics = latest_metrics(admin)
    assert metrics["companies"][0]["revenue_yesterday"] is None
    text_value = outbox_parts(admin)[0][0]
    assert "Выручка вчера: нет данных" in text_value
    assert "Выручка вчера: 0.00" not in text_value


def test_gap_digest_signals_match_manual_oracle(client, admin, app, fake, tmp_path) -> None:
    freeze(app, SCHEDULE_AT)
    _tenant, company_id = seed_gap_company(client, admin, app, fake, tmp_path)
    link_and_confirm(client, app, SCHEDULE_AT)
    schedule(app, SCHEDULE_AT)
    metrics = latest_metrics(admin)
    assert metrics["alerts"], "в gap_digest должны быть сигналы в сводке"
    types = {item["type"] for item in metrics["alerts"]}
    assert CASH_GAP.signal_type in types
    gap_card = metrics["companies"][0]
    assert gap_card["gap_date"] == CASH_GAP.gap_date
    assert gap_card["gap_amount"] == CASH_GAP.gap_amount
    text_value = "\n\n".join(part[0] for part in outbox_parts(admin))
    assert CASH_GAP.label_ru in text_value
    assert CASH_GAP.signal_type not in text_value
    for raw in expected_digest_signal_types():
        assert raw not in text_value
    for alert in metrics["alerts"]:
        assert alert["type"] not in text_value
        assert signal_type_label(alert["type"]) in text_value


def test_privacy_levels_and_counterparty(client, admin, app, fake, tmp_path) -> None:
    freeze(app, SCHEDULE_AT)
    company_id = seed_gap_company(client, admin, app, fake, tmp_path)[1]
    link_and_confirm(client, app, SCHEDULE_AT)
    assert client.post("/api/v1/telegram/digest-preview").status_code == 200
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
    assert PRIVACY_COUNTERPARTY_LABEL not in html.unescape(compact_line)
    assert PRIVACY_COUNTERPARTY_LABEL in html.unescape(full_line)
    assert NEW_COUNTERPARTY.signal_type not in full_line


def _urgent_polygon_services(client, admin, app, fake, tmp_path) -> str:
    _tenant, company_ids = seed_polygon(client, admin, app, fake, tmp_path)
    company_id = company_ids["services"]
    big_plan = client.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json={
            "direction": "out",
            "amount": "150000.00",
            "due_date": "2026-10-22",
            "expected_date": "2026-10-22",
        },
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert big_plan.status_code == 200, big_plan.text
    link_and_confirm(client, app, SCHEDULE_AT)
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
    return company_id


def _worsen_services_plan(client, company_id: str) -> None:
    smaller = client.post(
        f"/api/v1/companies/{company_id}/planned-cash",
        json={
            "direction": "out",
            "amount": "20000.00",
            "due_date": "2026-10-25",
            "expected_date": "2026-10-25",
        },
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert smaller.status_code == 200, smaller.text


def test_urgent_requires_prior_sent_materiality(client, admin, app, fake, tmp_path) -> None:
    """Сигнал: cash_gap. Срочное ухудшение только после отправленного materiality в outbox."""
    freeze(app, SCHEDULE_AT)
    _urgent_polygon_services(client, admin, app, fake, tmp_path)
    schedule(app, SCHEDULE_AT)
    assert _consider(app, SCHEDULE_AT) == 0


def test_urgent_after_digest_worsening(client, admin, app, fake, tmp_path) -> None:
    """Сигнал: cash_gap (ухудшение gap_amount после планового out)."""
    freeze(app, SCHEDULE_AT)
    company_id = _urgent_polygon_services(client, admin, app, fake, tmp_path)
    schedule(app, SCHEDULE_AT)
    dispatch(app, MockTelegram(), SCHEDULE_AT)
    _worsen_services_plan(client, company_id)
    at = SCHEDULE_AT + timedelta(hours=7)
    assert _consider(app, at) == 1
    assert _urgent_count(admin) == 1
    assert _consider(app, at + timedelta(hours=1)) == 0


def test_urgent_worsening_in_quiet_hours_is_zero(client, admin, app, fake, tmp_path) -> None:
    """Сигнал: cash_gap (ветка ухудшения; тихие часы)."""
    freeze(app, SCHEDULE_AT)
    company_id = _urgent_polygon_services(client, admin, app, fake, tmp_path)
    patch_subscription(client, {"quiet_start": "08:00", "quiet_end": "12:00"})
    schedule(app, SCHEDULE_AT)
    dispatch(app, MockTelegram(), SCHEDULE_AT)
    _worsen_services_plan(client, company_id)
    assert _consider(app, SCHEDULE_AT) == 0
    assert _urgent_count(admin) == 0


def test_both_mode_and_group_oracle_unchanged(client, admin, app, fake, tmp_path) -> None:
    freeze(app, SCHEDULE_AT)
    seed_polygon(client, admin, app, fake, tmp_path)
    link_and_confirm(client, app, SCHEDULE_AT)
    patch_subscription(client, {"mode": "both", "privacy_level": "compact"})
    schedule(app, SCHEDULE_AT)
    metrics = latest_metrics(admin)
    assert metrics["mode"] == "both"
    oracle = group_totals_oracle()
    assert metrics["totals"]["cash_total"] == oracle["cash_total"]
    assert metrics["totals"]["revenue_mtd"] == oracle["revenue_mtd"]
    text_value = "\n\n".join(part[0] for part in outbox_parts(admin))
    assert oracle["cash_total"] in text_value
    assert SERVICES.display_name in text_value
    assert_parts_within_telegram_limit(admin)


def test_unpaid_after_queue_cancels_dispatch(client, admin, app, fake, tmp_path) -> None:
    freeze(app, SCHEDULE_AT)
    _tenant, company_ids = seed_polygon(client, admin, app, fake, tmp_path)
    link_and_confirm(client, app, SCHEDULE_AT)
    schedule(app, SCHEDULE_AT)
    with admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE company_entitlements SET status = 'inactive', "
                "active_until = '2026-09-01T00:00:00+00:00' WHERE company_id = :cid"
            ),
            {"cid": company_ids["services"]},
        )
    transport = MockTelegram()
    dispatch(app, transport, SCHEDULE_AT)
    assert transport.sent == []
    assert sql_rows(admin, "SELECT status FROM notification_outbox LIMIT 1")[0][0] == "cancelled"


def test_group_revenue_oracle_still_46000(client, admin, app, fake, tmp_path) -> None:
    freeze(app, SCHEDULE_AT)
    seed_polygon(client, admin, app, fake, tmp_path)
    assert group_totals_oracle()["revenue_mtd"] == "46000.00"
    assert company_card_oracle("services")["revenue_mtd"] == "15000.00"
