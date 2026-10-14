import email
import imaplib
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any, cast

from app.config import Settings


class MailboxError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class MailAttachment:
    uidvalidity: int
    uid: int
    message_id: str
    sender: str
    folder: str
    filename: str
    content: bytes


class FakeMailbox:
    def __init__(self, messages: list[MailAttachment], *, fail: bool = False) -> None:
        self.messages = messages
        self.fail = fail
        self.checked = False

    def check(self) -> None:
        self.checked = True
        if self.fail:
            raise MailboxError("нет связи")

    def fetch(self, folder: str) -> list[MailAttachment]:
        if self.fail:
            raise MailboxError("нет связи")
        return [item for item in self.messages if item.folder == folder]


class ImapMailbox:
    """Боевой ящик. Создаётся только при включённом POLL_IMAP."""

    def __init__(self, host: str, username: str, password: str, port: int = 993) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.port = port

    def check(self) -> None:
        client = self._connect()
        try:
            client.logout()
        except imaplib.IMAP4.error:
            client.shutdown()

    def fetch(self, folder: str) -> list[MailAttachment]:
        client = self._connect()
        try:
            status, _ = client.select(folder, readonly=True)
            if status != "OK":
                raise MailboxError("папка недоступна")
            validity = _uidvalidity(client)
            found, data = client.uid("SEARCH", "ALL")
            if found != "OK" or not data or not data[0]:
                return []
            messages: list[MailAttachment] = []
            for raw_uid in data[0].split():
                fetched, payload = client.uid("FETCH", raw_uid, "(RFC822)")
                if fetched != "OK" or not payload or not isinstance(payload[0], tuple):
                    continue
                messages.extend(_parts(payload[0][1], validity, int(raw_uid), folder))
            return messages
        finally:
            try:
                client.logout()
            except imaplib.IMAP4.error:
                client.shutdown()

    def _connect(self) -> imaplib.IMAP4_SSL:
        try:
            client = imaplib.IMAP4_SSL(self.host, self.port)
            client.login(self.username, self.password)
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailboxError("нет связи") from exc
        return client


def open_imap(settings: Settings, host: str, username: str, password: str) -> ImapMailbox | None:
    if not settings.poll_imap:
        return None
    return ImapMailbox(host, username, password)


def _uidvalidity(client: imaplib.IMAP4_SSL) -> int:
    responses = cast(dict[Any, Any], client.untagged_responses)
    raw_list = responses.get(b"UIDVALIDITY") or responses.get("UIDVALIDITY") or [b"0"]
    raw = raw_list[-1]
    if isinstance(raw, bytes):
        return int(raw)
    return 0


def _parts(raw: bytes, uidvalidity: int, uid: int, folder: str) -> list[MailAttachment]:
    message = email.message_from_bytes(raw)
    sender = parseaddr(message.get("From", ""))[1]
    message_id = message.get("Message-ID", "") or ""
    found: list[MailAttachment] = []
    for part in message.walk():
        if part.get_content_disposition() != "attachment":
            continue
        payload = part.get_payload(decode=True)
        content = payload if isinstance(payload, bytes) else b""
        found.append(
            MailAttachment(
                uidvalidity=uidvalidity,
                uid=uid,
                message_id=message_id,
                sender=sender,
                folder=folder,
                filename=part.get_filename() or "attachment",
                content=content,
            )
        )
    if found:
        return found
    return [
        MailAttachment(
            uidvalidity=uidvalidity,
            uid=uid,
            message_id=message_id,
            sender=sender,
            folder=folder,
            filename="",
            content=b"",
        )
    ]
