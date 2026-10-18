from datetime import timedelta
from uuid import UUID

from app.config import Settings
from app.errors import AppError
from app.integrations.imap_client import MailAttachment, MailboxError, open_imap
from app.jobs.finance import assert_financial_job
from app.models.identity import Company, Membership, User
from app.models.imports import EmailIngestion, ImportBatch, SourceConnection
from app.security.access import OWNER, require_membership
from app.security.context import set_context
from app.security.mailbox_crypto import decrypt_secret
from app.services.import_service import receive_import
from app.services.ingestion_delivery_service import (
    PART_FAILED,
    PART_IGNORED,
    PART_PREVIEW,
    PART_SKIPPED,
    TransportContext,
    get_or_create_part,
    group_mail_attachments,
    link_part_to_batch,
    mail_delivery_key,
    mail_manifest,
    mail_part_idempotency_key,
    refresh_delivery_transport_status,
    resolve_delivery,
)
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
    for (_uidvalidity, _uid), attachments in group_mail_attachments(messages).items():
        if _ingest_message(
            session,
            settings,
            connection,
            membership,
            company,
            user,
            attachments,
            sender,
            at,
        ):
            saved += 1
    connection.last_attempt_at = at
    connection.last_error = None
    connection.next_attempt_at = at + timedelta(minutes=connection.poll_interval_minutes)
    session.flush()
    return saved


def _ingest_message(
    session,
    settings,
    connection: SourceConnection,
    membership: Membership,
    company: Company,
    user: User,
    attachments: list[MailAttachment],
    sender: str,
    at,
) -> bool:
    if not attachments:
        return False
    head = attachments[0]
    manifest_fp, indexed = mail_manifest(connection.id, attachments)
    delivery = resolve_delivery(
        session,
        company,
        connection,
        channel="email",
        delivery_key=mail_delivery_key(connection.id, head.uidvalidity, head.uid),
        request_fingerprint=manifest_fp,
        at=at,
    )
    touched = False
    for (part_index, digest), attachment in zip(indexed, attachments, strict=True):
        if _email_attachment_seen(session, connection, attachment, digest):
            part = get_or_create_part(
                session,
                delivery,
                part_index=part_index,
                content_hash=digest,
                at=at,
            )
            if part.part_status == PART_PREVIEW:
                part.part_status = PART_SKIPPED
                part.updated_at = at
            continue
        part = get_or_create_part(
            session,
            delivery,
            part_index=part_index,
            content_hash=digest,
            at=at,
        )
        if part.part_status == PART_PREVIEW and part.batch_id is not None:
            _email_row(
                session,
                connection,
                attachment,
                digest,
                "preview",
                part.batch_id,
                delivery.id,
                at,
            )
            touched = True
            continue
        if attachment.sender.casefold() != sender.casefold() or not attachment.content:
            part.part_status = PART_IGNORED
            part.error_code = "ignored_sender"
            part.updated_at = at
            _email_row(session, connection, attachment, digest, "ignored", None, delivery.id, at)
            continue
        try:
            payload = receive_import(
                session,
                membership,
                company,
                user,
                settings,
                connection_id=connection.id,
                content=attachment.content,
                idempotency_key=mail_part_idempotency_key(
                    connection.id, attachment.uidvalidity, attachment.uid, part_index, digest
                ),
                at=at,
                transport=TransportContext(delivery_id=delivery.id, part_id=part.id),
                skip_http_idempotency=True,
            )
        except AppError as exc:
            if exc.code in {"unsupported_format", "payload_too_large"}:
                part.part_status = PART_FAILED
                part.error_code = exc.code
                part.updated_at = at
                _email_row(session, connection, attachment, digest, "failed", None, delivery.id, at)
                continue
            part.part_status = PART_FAILED
            part.error_code = exc.code
            part.updated_at = at
            raise
        batch_id = UUID(payload["id"])
        batch = session.get(ImportBatch, batch_id)
        if batch is None:
            raise AppError(404, "not_found", "Партия не найдена")
        link_part_to_batch(
            session,
            part,
            batch,
            part_status=PART_PREVIEW,
            error_code=None,
            at=at,
        )
        _email_row(session, connection, attachment, digest, "preview", batch_id, delivery.id, at)
        touched = True
    refresh_delivery_transport_status(session, delivery.id, at)
    return touched


def _email_attachment_seen(
    session, connection: SourceConnection, message: MailAttachment, digest: str
) -> bool:
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


def _email_row(
    session,
    connection,
    message: MailAttachment,
    digest,
    status,
    batch_id,
    delivery_id,
    at,
) -> None:
    session.add(
        EmailIngestion(
            tenant_id=connection.tenant_id,
            connection_id=connection.id,
            batch_id=None if batch_id is None else batch_id,
            delivery_id=delivery_id,
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
