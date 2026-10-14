from decimal import Decimal
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    public_base_url: str = "http://localhost:5173"
    cors_origins: str = "http://localhost:5173"
    database_url: str = "postgresql+psycopg://finpilot_app:change-me@127.0.0.1:5432/finpilot"
    worker_database_url: str = (
        "postgresql+psycopg://finpilot_worker:change-me@127.0.0.1:5432/finpilot"
    )
    migration_database_url: str = "postgresql+psycopg://127.0.0.1:5432/finpilot"
    redis_url: str = "redis://127.0.0.1:6379/0"
    rate_limit_backend: str = "memory"
    session_secret: str = "dev-only-change-me"
    secret_encryption_key: str = "dev-only-change-me"
    session_cookie_name: str = "fp_session"
    session_cookie_secure: bool = False
    session_idle_minutes: int = 720
    session_absolute_hours: int = 336
    send_external_messages: bool = False
    poll_imap: bool = False
    billing_enabled: bool = True
    billing_mode: str = "test"
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_return_url: str = ""
    yookassa_api_base: str = "https://api.yookassa.ru/v3"
    yookassa_ip_allowlist: str = ""
    trust_proxy: bool = False
    send_live_payments: bool = False
    receipt_mode: str = ""
    billing_grace_days: int = 3
    annual_billing_enabled: bool = True
    annual_discount_percent: Decimal = Decimal("15.00")
    annual_renewal_reminder_days: str = "30,7,1"
    monthly_renewal_reminder_days: str = "3,1,0"
    email_provider_mode: str = "mock"
    send_real_email: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    billing_guard_bypass: bool = False
    refunds_enabled: bool = False
    billing_staff_emails: str = ""
    outbound_email_allowlist: str = ""
    telegram_chat_allowlist: str = ""
    bot_token: str = ""
    bot_username: str = ""
    telegram_webhook_secret: str = ""
    quote_ttl_minutes: int = 15
    webhook_max_bytes: int = 1_000_000
    webhook_rate_limit: int = Field(default=60)
    import_storage_dir: str = "var/imports"
    import_max_bytes: int = 20 * 1024 * 1024
    import_max_rows: int = 100_000
    import_max_uncompressed_bytes: int = 50 * 1024 * 1024

    @field_validator("app_env")
    @classmethod
    def _env(cls, value: str) -> str:
        allowed = {"development", "test", "production"}
        if value not in allowed:
            raise ValueError("неизвестное окружение")
        return value

    def model_post_init(self, context: object) -> None:
        if self.app_env != "production":
            return
        if self.email_provider_mode == "mock":
            raise ValueError("mock email запрещён в production")
        if self.session_secret == "dev-only-change-me":
            raise ValueError("нужен боевой session secret")
        if self.billing_guard_bypass:
            raise ValueError("обход billing guard запрещён в production")
        if self.poll_imap and self.secret_encryption_key == "dev-only-change-me":
            raise ValueError("нужен ключ шифрования почты")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def annual_reminder_days(self) -> set[int]:
        return _parse_days(self.annual_renewal_reminder_days)

    @property
    def monthly_reminder_days(self) -> set[int]:
        return _parse_days(self.monthly_renewal_reminder_days)

    @property
    def staff_emails(self) -> set[str]:
        raw = self.billing_staff_emails.split(",")
        return {item.strip().lower() for item in raw if item.strip()}

    @property
    def allowed_outbound_emails(self) -> set[str]:
        raw = self.outbound_email_allowlist.split(",")
        return {item.strip().casefold() for item in raw if item.strip()}

    @property
    def allowed_telegram_chats(self) -> set[int]:
        chats: set[int] = set()
        for item in self.telegram_chat_allowlist.split(","):
            raw = item.strip()
            if not raw:
                continue
            try:
                chats.add(int(raw))
            except ValueError:
                continue
        return chats

    def email_recipient_allowed(self, address: str) -> bool:
        normalized = address.strip().casefold()
        if not normalized:
            return False
        return normalized in self.allowed_outbound_emails

    @property
    def yookassa_ips(self) -> set[str]:
        return {item.strip() for item in self.yookassa_ip_allowlist.split(",") if item.strip()}

    def billing_bypass_allowed(self) -> bool:
        return self.billing_guard_bypass and self.app_env != "production"


def _parse_days(raw: str) -> set[int]:
    return {int(item) for item in raw.split(",") if item.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
