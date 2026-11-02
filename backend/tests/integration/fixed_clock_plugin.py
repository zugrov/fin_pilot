"""Pytest: серверное время через TEST_FIXED_CLOCK_ISO (FixedClock на app)."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from app.clock import FixedClock


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "fixed_clock(iso): подменить app.state.clock на FixedClock(iso) для теста",
    )


@pytest.fixture(autouse=True)
def _integration_fixed_clock(request: pytest.FixtureRequest) -> None:
    if "app" not in request.fixturenames:
        return
    marker = request.node.get_closest_marker("fixed_clock")
    raw = ""
    if marker is not None:
        raw = str(marker.args[0]) if marker.args else ""
    if not raw:
        raw = os.environ.get("TEST_FIXED_CLOCK_ISO", "").strip()
    if not raw:
        return
    app = request.getfixturevalue("app")
    moment = datetime.fromisoformat(raw)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    app.state.clock = FixedClock(moment)
