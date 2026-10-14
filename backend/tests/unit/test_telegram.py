from datetime import UTC, datetime, time
from decimal import Decimal

from app.config import Settings
from app.domain.telegram_text import (
    SlotState,
    escape_html,
    local_to_utc,
    materiality_worsened,
    slot_state,
    split_parts,
)
from app.integrations.telegram import build_transport, polling_allowed
from app.main import create_app
from app.services.telegram_digest import _totals


def test_dst_gap_moves_forward_and_fold_is_one_instant() -> None:
    missing = local_to_utc(datetime(2026, 3, 8).date(), time(2, 30), "America/New_York")
    local = missing.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
    assert local.hour == 3
    first = local_to_utc(datetime(2026, 11, 1).date(), time(1, 30), "America/New_York")
    second = local_to_utc(datetime(2026, 11, 1).date(), time(1, 30), "America/New_York")
    assert first == second


def test_catch_up_window_and_worsening() -> None:
    zone = "Europe/Moscow"
    morning = datetime(2026, 10, 14, 5, 30, tzinfo=UTC)
    late = datetime(2026, 10, 14, 8, 0, tzinfo=UTC)
    assert slot_state(morning, time(8, 30), zone, [1, 2, 3, 4, 5, 6, 7])[0] == SlotState.DUE
    assert slot_state(late, time(8, 30), zone, [1, 2, 3, 4, 5, 6, 7])[0] == SlotState.MISSED
    assert materiality_worsened(Decimal("100.00"), Decimal("120.00"))
    assert not materiality_worsened(Decimal("100.00"), Decimal("110.00"))


def test_parts_escape_html_and_stay_within_limit() -> None:
    assert "<" not in escape_html("<Альфа>")
    block = escape_html("A" * 20 + "<tag>") + (" слово" * 800)
    parts = split_parts([block, "хвост"], limit=3500)
    assert parts
    assert all(len(part) <= 3500 for part in parts)
    assert all("<tag>" not in part for part in parts)
    assert "&lt;tag&gt;" in "".join(parts)


def test_t10_app_starts_without_bot_token() -> None:
    settings = Settings(
        bot_token="",
        telegram_webhook_secret="",
        send_external_messages=False,
        app_env="test",
    )
    application = create_app(settings)
    try:
        assert application.state.settings.bot_token == ""
        assert build_transport(settings) is None
        assert polling_allowed(settings) is False
    finally:
        application.state.engine.dispose()
        application.state.worker_engine.dispose()


def test_empty_group_totals_are_unavailable() -> None:
    totals = _totals([], False)
    assert totals["cash_total"] is None
    assert totals["revenue_yesterday"] is None
    assert totals["net"] is None
