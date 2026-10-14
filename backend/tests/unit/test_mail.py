from datetime import UTC, datetime

from app.config import Settings
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


def test_password_roundtrip_is_not_stored_as_plaintext() -> None:
    settings = Settings(app_env="test", secret_encryption_key="dev-only-change-me")
    token = encrypt_secret(settings, "mailbox-secret-1")
    assert "mailbox-secret-1" not in token
    assert decrypt_secret(settings, token) == "mailbox-secret-1"
