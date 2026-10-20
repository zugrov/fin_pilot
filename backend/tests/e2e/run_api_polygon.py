"""Uvicorn для E2E полигона (FixedClock = POLYGON_FROZEN_ISO)."""

from __future__ import annotations

import uvicorn
from app.clock import FixedClock
from app.integrations.payments import FakeYooKassa
from app.main import create_app
from tests.e2e.env import apply_e2e_env, assert_finpilot_test_only
from tests.e2e.settings import E2ESettings
from tests.synthetic_polygon.constants import polygon_frozen_moment


def build_app():
    port = apply_e2e_env()
    assert_finpilot_test_only(port)
    settings = E2ESettings()
    application = create_app(settings)
    application.state.clock = FixedClock(polygon_frozen_moment())
    fake = FakeYooKassa(shop_id="shop-test")
    application.state.payment_provider_factory = lambda: fake
    return application


def main() -> None:
    uvicorn.run(
        "tests.e2e.run_api_polygon:build_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
