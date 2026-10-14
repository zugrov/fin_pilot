from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class SendOutcome:
    kind: str
    message_id: int | None = None
    retry_after: int = 0
    error: str = ""


class MockTelegram:
    def __init__(self, script: list[SendOutcome] | None = None) -> None:
        self.script = list(script or [])
        self.sent: list[dict] = []

    def send(self, chat_id: int, payload: dict) -> SendOutcome:
        self.sent.append({"chat_id": chat_id, "payload": payload})
        if self.script:
            return self.script.pop(0)
        return SendOutcome("sent", message_id=len(self.sent))


class BotApiTelegram:
    def __init__(self, token: str, allowed_chats: set[int]) -> None:
        self._token = token
        self._allowed_chats = allowed_chats

    def send(self, chat_id: int, payload: dict) -> SendOutcome:
        if chat_id not in self._allowed_chats:
            return SendOutcome("failed", error="recipient")
        body = {
            "chat_id": chat_id,
            "text": payload["text"],
            "parse_mode": "HTML",
            "protect_content": True,
        }
        buttons = payload.get("buttons") or []
        if buttons:
            body["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": item["label"], "url": item["url"]}]
                    for item in buttons
                    if "url" in item
                ]
            }
        try:
            response = httpx.post(
                f"https://api.telegram.org/bot{self._token}/sendMessage",
                json=body,
                timeout=10,
            )
        except httpx.TimeoutException:
            return SendOutcome("unknown", error="timeout")
        except httpx.HTTPError as exc:
            return SendOutcome("retry", error=str(exc))
        if response.status_code == 429:
            retry_after = 1
            try:
                retry_after = int(response.json().get("parameters", {}).get("retry_after", 1))
            except (TypeError, ValueError):
                retry_after = 1
            return SendOutcome("retry", retry_after=retry_after, error="429")
        if response.status_code == 403:
            return SendOutcome("forbidden", error="403")
        if response.status_code == 400:
            return SendOutcome("failed", error="formatting")
        if response.status_code >= 500:
            return SendOutcome("retry", error=str(response.status_code))
        if response.status_code != 200:
            return SendOutcome("failed", error=str(response.status_code))
        message_id = response.json().get("result", {}).get("message_id")
        return SendOutcome("sent", message_id=None if message_id is None else int(message_id))


def build_transport(settings) -> BotApiTelegram | None:
    if settings.send_external_messages and settings.bot_token:
        return BotApiTelegram(settings.bot_token, settings.allowed_telegram_chats)
    return None


def polling_allowed(settings) -> bool:
    return bool(
        settings.bot_token
        and not settings.telegram_webhook_secret
        and settings.app_env == "development"
        and settings.send_external_messages
    )
