from datetime import UTC, datetime

import pytest
from app.config import Settings
from app.errors import AppError
from app.integrations.email import EmailMessage, SmtpEmailProvider
from app.integrations.imap_client import open_imap
from app.security.mailbox_crypto import decrypt_secret, encrypt_secret
from app.services.mail_service import poll_mailboxes


def test_poll_does_not_open_a_socket_when_disabled(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("сокет")

    monkeypatch.setattr("imaplib.IMAP4_SSL", boom)
    settings = Settings(poll_imap=False, app_env="test", secret_encryption_key="dev-only-change-me")
    assert poll_mailboxes(None, settings, datetime(2026, 10, 14, tzinfo=UTC)) == 0
    assert open_imap(settings, "imap.example.com", "box@example.com", "secret") is None


def test_smtp_refuses_address_outside_allowlist(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("smtp")

    monkeypatch.setattr("smtplib.SMTP", boom)
    empty = Settings(app_env="test", send_real_email=True, smtp_host="smtp.example.com")
    listed = Settings(
        app_env="test",
        send_real_email=True,
        smtp_host="smtp.example.com",
        outbound_email_allowlist="Pilot@Example.com",
    )
    message = EmailMessage("other@example.com", "notice", {})
    with pytest.raises(AppError) as caught:
        SmtpEmailProvider(empty).send(message)
    assert caught.value.code == "recipient_not_allowed"
    with pytest.raises(AppError) as listed_miss:
        SmtpEmailProvider(listed).send(message)
    assert listed_miss.value.code == "recipient_not_allowed"
    assert listed.email_recipient_allowed("pilot@example.com")


def test_auth_mail_sends_link_and_refuses_empty_link(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, timeout: int = 20) -> None:
            captured["host"] = host
            captured["port"] = str(port)

        def __enter__(self) -> "FakeSMTP":
            return self

        def __exit__(self, *_args: object) -> bool:
            return False

        def starttls(self) -> None:
            captured["tls"] = "yes"

        def login(self, username: str, password: str) -> None:
            raise AssertionError("login")

        def send_message(self, mime) -> None:
            captured["subject"] = str(mime["Subject"])
            captured["body"] = str(mime.get_content())

    monkeypatch.setattr("smtplib.SMTP", FakeSMTP)
    settings = Settings(
        app_env="test",
        send_real_email=True,
        smtp_host="smtp.example.com",
        smtp_from="finpilot@example.com",
        outbound_email_allowlist="pilot@example.com",
    )
    link = "http://127.0.0.1:8090/verify-email?token=one-time"
    SmtpEmailProvider(settings).send(
        EmailMessage("pilot@example.com", "verify_email", {"link": link})
    )
    assert captured["body"].strip() == link
    assert captured["subject"] == "Подтверждение почты"
    assert "one-time" not in captured["subject"]
    assert captured["tls"] == "yes"

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("smtp")

    monkeypatch.setattr("smtplib.SMTP", boom)
    with pytest.raises(AppError) as caught:
        SmtpEmailProvider(settings).send(
            EmailMessage("pilot@example.com", "reset_password", {})
        )
    assert caught.value.code == "missing_link"


def test_password_roundtrip_is_not_stored_as_plaintext() -> None:
    settings = Settings(app_env="test", secret_encryption_key="dev-only-change-me")
    token = encrypt_secret(settings, "mailbox-secret-1")
    assert "mailbox-secret-1" not in token
    assert decrypt_secret(settings, token) == "mailbox-secret-1"
