"""Uvicorn entry для локального/CI E2E (127.0.0.1 only)."""

from __future__ import annotations

from datetime import UTC, datetime

import uvicorn
from app.clock import FixedClock
from app.integrations.payments import FakeYooKassa
from app.main import create_app
from tests.e2e.constants import E2E_FROZEN_ISO
from tests.e2e.env import apply_e2e_env, assert_finpilot_test_only
from tests.e2e.settings import E2ESettings


def build_app():
    port = apply_e2e_env()
    assert_finpilot_test_only(port)
    settings = E2ESettings()
    application = create_app(settings)
    frozen = datetime.fromisoformat(E2E_FROZEN_ISO)
    if frozen.tzinfo is None:
        frozen = frozen.replace(tzinfo=UTC)
    application.state.clock = FixedClock(frozen)
    fake = FakeYooKassa(shop_id="shop-test")
    application.state.payment_provider_factory = lambda: fake
    return application


def main() -> None:
    uvicorn.run(
        "tests.e2e.run_api:build_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
