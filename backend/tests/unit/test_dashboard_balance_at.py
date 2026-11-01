from datetime import UTC, date, datetime

from app.services.report_service import dashboard_balance_at


def test_dashboard_balance_at_caps_future_period_end_to_now() -> None:
    now = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
    moment = dashboard_balance_at(date(2026, 10, 31), "Europe/Moscow", now)
    assert moment == now


def test_dashboard_balance_at_uses_period_end_when_before_now() -> None:
    now = datetime(2026, 11, 1, 6, 0, tzinfo=UTC)
    moment = dashboard_balance_at(date(2026, 8, 31), "Europe/Moscow", now)
    assert moment.date() == date(2026, 8, 31)
    assert moment > datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
