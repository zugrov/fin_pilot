from typing import Protocol

from app.config import Settings
from app.errors import AppError


class EmailMessage:
    def __init__(self, to_email: str, template_key: str, payload: dict) -> None:
        self.to_email = to_email
        self.template_key = template_key
        self.payload = payload


class EmailProvider(Protocol):
    def send(self, message: EmailMessage) -> None: ...


class MockEmailProvider:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


class SmtpEmailProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def send(self, message: EmailMessage) -> None:
        if not self._settings.send_real_email:
            raise AppError(403, "email_disabled", "Реальная почта выключена")
        if not self._settings.email_recipient_allowed(message.to_email):
            raise AppError(403, "recipient_not_allowed", "Получатель не в списке")
        import smtplib
        from email.message import EmailMessage as MimeMessage

        mime = MimeMessage()
        mime["From"] = self._settings.smtp_from
        mime["To"] = message.to_email
        mime["Subject"] = message.template_key
        mime.set_content(message.template_key)
        with smtplib.SMTP(self._settings.smtp_host, self._settings.smtp_port, timeout=20) as smtp:
            smtp.starttls()
            if self._settings.smtp_username:
                smtp.login(self._settings.smtp_username, self._settings.smtp_password)
            smtp.send_message(mime)


def build_email_provider(settings: Settings) -> EmailProvider:
    if settings.app_env == "production" and settings.email_provider_mode == "mock":
        raise RuntimeError("mock email запрещён в production")
    if settings.email_provider_mode == "smtp":
        return SmtpEmailProvider(settings)
    if settings.app_env == "production":
        raise RuntimeError("mock email запрещён в production")
    return MockEmailProvider()
