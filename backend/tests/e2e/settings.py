from __future__ import annotations

from app.config import Settings
from pydantic_settings import SettingsConfigDict


class E2ESettings(Settings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    app_env: str = "test"
    balances_import_enabled: bool = True
    billing_guard_bypass: bool = False
