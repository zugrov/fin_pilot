import hashlib
from datetime import timedelta
from uuid import UUID

from app.config import Settings
from app.errors import AppError
from app.integrations.imap_client import MailAttachment, MailboxError, open_imap
from app.jobs.finance import assert_financial_job
from app.models.identity import Company, Membership, User
from app.models.imports import EmailIngestion, SourceConnection
from app.security.access import OWNER, require_membership
from app.security.context import set_context
from app.security.mailbox_crypto import decrypt_secret
from app.services.import_service import receive_import
from sqlalchemy import select, text
from sqlalchemy.orm import Session


def email_source(session: Session, company: Company, source_id) -> SourceConnection:
    row = session.get(SourceConnection, source_id)
    if row is None or row.tenant_id != company.tenant_id or row.company_id != company.id:
        raise AppError(404, "not_found", "Источник не найден")
    if row.type != "email":
        raise AppError(422, "validation_error", "Это не почтовый источник")
    return row


def test_mailbox(settings: Settings, connection: SourceConnection, mailbox=None) -> dict:
    chosen = mailbox if mailbox is not None else _live(settings, connection)
    chosen.check()
    return {"status": "ok", "saved": False}


def sync_mailbox(
    session: Session,
    settings: Settings,
    connection: SourceConnection,
    user: User,
    at,
    mailbox=None,
) -> dict:
    chosen = mailbox if mailbox is not None else _live(settings, connection)
    saved = ingest_mailbox(session, settings, connection, chosen, user, at)
    return {"status": "ok", "saved": saved}


def poll_mailboxes(session: Session, settings: Settings, at) -> int:
    if not settings.poll_imap:
        return 0
    rows = (
        session.execute(text("SELECT * FROM app_list_email_sources(:at)"), {"at": at})
        .mappings()
        .all()
    )
    saved = 0
    for row in rows:
        set_context(session, tenant_id=row["source_tenant_id"], user_id=None)
        connection = session.get(SourceConnection, row["source_id"])
        user = None if connection is None else _owner(session, connection.tenant_id)
        if connection is None or user is None:
            continue
        try:
            assert_financial_job(
                session,
                user_id=user.id,
                tenant_id=connection.tenant_id,
                company_id=connection.company_id,
                at=at,
                grace_days=settings.billing_grace_days,
                bypass=settings.billing_bypass_allowed(),
            )
        except AppError:
            _defer(connection, at, "нет прав")
            continue
        try:
            mailbox = _live(settings, connection)
        except AppError as exc:
            _defer(connection, at, exc.message)
            continue
        saved += ingest_mailbox(session, settings, connection, mailbox, user, at)
    return saved


def ingest_mailbox(session, settings, connection: SourceConnection, mailbox, user: User, at) -> int:
    """Сначала читает ящик, затем пишет preview. Письмо само не проводится."""
    folder = str((connection.config_redacted or {}).get("folder") or "")
    sender = str((connection.config_redacted or {}).get("sender") or "")
    try:
        messages = mailbox.fetch(folder)
    except MailboxError:
        _defer(connection, at, "нет связи")
        return 0
    set_context(session, tenant_id=connection.tenant_id, user_id=user.id)
    membership = require_membership(session, user.id, connection.tenant_id)
    company = session.get(Company, connection.company_id)
    if company is None:
        _defer(connection, at, "фирма не найдена")
        return 0
    saved = 0
    for message in messages:
        if _remember(session, settings, connection, membership, company, user, message, sender, at):
            saved += 1
    connection.last_attempt_at = at
    connection.last_error = None
    connection.next_attempt_at = at + timedelta(minutes=connection.poll_interval_minutes)
    session.flush()
    return saved


def _remember(
    session,
    settings,
    connection: SourceConnection,
    membership: Membership,
    company: Company,
    user: User,
    message: MailAttachment,
    sender: str,
    at,
) -> bool:
    digest = hashlib.sha256(message.content).hexdigest()
    if _seen(session, connection, message, digest):
        return False
    if message.sender.casefold() != sender.casefold() or not message.content:
        _row(session, connection, message, digest, "ignored", None, at)
        return False
    try:
        payload = receive_import(
            session,
            membership,
            company,
            user,
            settings,
            connection_id=connection.id,
            content=message.content,
            idempotency_key=f"mail:{connection.id}:{message.uid}:{digest[:16]}",
            at=at,
        )
    except AppError as exc:
        if exc.code in {"unsupported_format", "payload_too_large"}:
            _row(session, connection, message, digest, "failed", None, at)
            return False
        raise
    _row(session, connection, message, digest, "preview", UUID(payload["id"]), at)
    return True


def _seen(session, connection: SourceConnection, message: MailAttachment, digest: str) -> bool:
    found = session.scalar(
        select(EmailIngestion.id).where(
            EmailIngestion.tenant_id == connection.tenant_id,
            EmailIngestion.connection_id == connection.id,
            EmailIngestion.uidvalidity == message.uidvalidity,
            EmailIngestion.uid == message.uid,
            EmailIngestion.attachment_hash == digest,
        )
    )
    return found is not None


def _row(session, connection, message: MailAttachment, digest, status, batch_id, at) -> None:
    session.add(
        EmailIngestion(
            tenant_id=connection.tenant_id,
            connection_id=connection.id,
            batch_id=None if batch_id is None else batch_id,
            uidvalidity=message.uidvalidity,
            uid=message.uid,
            message_id=message.message_id or None,
            attachment_hash=digest,
            status=status,
            created_at=at,
        )
    )
    session.flush()


def _defer(connection: SourceConnection, at, reason: str) -> None:
    connection.last_attempt_at = at
    connection.last_error = reason
    connection.next_attempt_at = at + timedelta(minutes=connection.poll_interval_minutes)


def _live(settings: Settings, connection: SourceConnection):
    mailbox = None
    config = connection.config_redacted or {}
    if connection.encrypted_credentials:
        mailbox = open_imap(
            settings,
            str(config.get("host") or ""),
            str(config.get("username") or ""),
            decrypt_secret(settings, connection.encrypted_credentials),
        )
    if mailbox is None:
        raise AppError(409, "imap_disabled", "Опрос почты выключен")
    return mailbox


def _owner(session: Session, tenant_id) -> User | None:
    membership = session.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.role == OWNER,
            Membership.status == "active",
        )
    )
    if membership is None:
        return None
    return session.get(User, membership.user_id)
