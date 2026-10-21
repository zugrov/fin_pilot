from datetime import timedelta
from uuid import UUID

from app.config import Settings
from app.errors import AppError
from app.integrations.telegram import SendOutcome
from app.jobs.finance import assert_financial_job
from app.models.identity import User
from app.models.telegram import DigestSubscription, NotificationOutbox, TelegramBinding
from app.security.context import set_context
from app.services.telegram_binding import revoke_binding
from sqlalchemy import select, text
from sqlalchemy.orm import Session


def dispatch_outbox(session: Session, settings: Settings, transport, at) -> int:
    session.execute(text("SELECT app_expire_notification_leases(:at)"), {"at": at})
    if transport is None:
        return 0
    claimed = session.execute(
        text("SELECT * FROM app_claim_notification_outbox(:at, :limit)"),
        {"at": at, "limit": 20},
    ).mappings().all()
    handled = 0
    for row in claimed:
        set_context(session, tenant_id=row["tenant_id"], user_id=None)
        item = session.get(NotificationOutbox, row["id"])
        if item is None:
            continue
        binding = session.get(TelegramBinding, item.binding_id)
        user = None if binding is None else session.get(User, binding.user_id)
        if binding is None or user is None or binding.status != "active":
            _cancel(item, "binding")
            handled += 1
            continue
        set_context(session, tenant_id=item.tenant_id, user_id=user.id)
        if not _allowed(session, settings, item, binding, user, at):
            set_context(session, tenant_id=item.tenant_id, user_id=user.id)
            _cancel(item, "access")
            handled += 1
            continue
        outcome = transport.send(binding.chat_id, item.payload)
        _apply(session, item, binding, outcome, at)
        handled += 1
    return handled


def _allowed(session, settings, item: NotificationOutbox, binding, user: User, at) -> bool:
    if item.snapshot_id is not None:
        subscription = session.scalar(
            select(DigestSubscription).where(DigestSubscription.binding_id == binding.id)
        )
        if subscription is None or not subscription.enabled:
            return False
    company_ids = list((item.payload or {}).get("company_ids") or [])
    if not company_ids:
        return False
    for company_id in company_ids:
        try:
            assert_financial_job(
                session,
                user_id=user.id,
                tenant_id=item.tenant_id,
                company_id=UUID(str(company_id)),
                at=at,
                grace_days=settings.billing_grace_days,
                bypass=settings.billing_bypass_allowed(),
                mode="send",
            )
        except AppError:
            return False
    return True


def _apply(
    session, item: NotificationOutbox, binding: TelegramBinding, outcome: SendOutcome, at
) -> None:
    item.attempts += 1
    if outcome.kind == "sent":
        item.status = "sent"
        item.telegram_message_id = outcome.message_id
        item.sent_at = at
        item.lease_until = None
        item.last_error = None
        return
    if outcome.kind == "forbidden":
        item.status = "cancelled"
        item.last_error = "403"
        item.lease_until = None
        revoke_binding(session, binding, at)
        return
    if outcome.kind == "unknown":
        item.status = "unknown"
        item.last_error = outcome.error or "unknown"
        item.lease_until = None
        return
    if outcome.kind == "failed":
        item.status = "failed"
        item.last_error = outcome.error or "failed"
        item.lease_until = None
        return
    delay = outcome.retry_after if outcome.retry_after > 0 else min(30 * item.attempts, 900)
    item.status = "retry"
    item.last_error = outcome.error or "retry"
    item.lease_until = None
    item.next_attempt_at = at + timedelta(seconds=delay)


def _cancel(item: NotificationOutbox, reason: str) -> None:
    item.status = "cancelled"
    item.last_error = reason
    item.lease_until = None
