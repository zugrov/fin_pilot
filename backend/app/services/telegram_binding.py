import uuid
from datetime import time, timedelta
from zoneinfo import ZoneInfo

from app.config import Settings
from app.domain.telegram_text import timezone_or_none
from app.errors import AppError
from app.models.identity import AuditLog, Company, Membership, User
from app.models.telegram import (
    DigestSubscription,
    NotificationOutbox,
    TelegramBinding,
    TelegramLinkToken,
)
from app.security.access import companies_for
from app.security.context import set_context
from app.security.tokens import new_secret
from sqlalchemy import select
from sqlalchemy.orm import Session

TOKEN_TTL = timedelta(minutes=10)
DEFAULT_TIME = time(8, 30)
DEFAULT_DAYS = [1, 2, 3, 4, 5, 6, 7]


def issue_token(
    session: Session, membership: Membership, user: User, settings: Settings, at
) -> dict:
    if user.email_verified_at is None:
        raise AppError(403, "email_not_verified", "Подтвердите почту")
    raw, digest = new_secret()
    if len(raw) > 64:
        raise AppError(500, "internal", "Токен привязки слишком длинный")
    row = TelegramLinkToken(
        tenant_id=membership.tenant_id,
        user_id=user.id,
        token_hash=digest,
        expires_at=at + TOKEN_TTL,
        used_at=None,
        created_at=at,
    )
    session.add(row)
    session.flush()
    _audit(session, user, membership.tenant_id, "telegram_link_issued", row.id, at)
    username = settings.bot_username.strip().lstrip("@")
    deep_link = None if not username else f"https://t.me/{username}?start={raw}"
    return {
        "token": raw,
        "expires_at": row.expires_at.isoformat(),
        "deep_link": deep_link,
    }


def binding_view(session: Session, membership: Membership, user: User) -> dict:
    row = _current(session, membership, user)
    if row is None:
        return {"status": "none"}
    return _binding_payload(row)


def confirm_binding(session: Session, membership: Membership, user: User, at) -> dict:
    if user.email_verified_at is None:
        raise AppError(403, "email_not_verified", "Подтвердите почту")
    pending = _by_status(session, membership, user, "pending")
    if pending is None:
        raise AppError(404, "not_found", "Ожидающая привязка не найдена")
    active = _by_status(session, membership, user, "active")
    if active is not None:
        active.status = "revoked"
        active.revoked_at = at
        _disable_subscription(session, active, at)
        _cancel_queue(session, active, at)
    pending.status = "active"
    pending.linked_at = at
    session.flush()
    _ensure_subscription(session, pending, at)
    _audit(session, user, membership.tenant_id, "telegram_binding_confirmed", pending.id, at)
    return _binding_payload(pending)


def unlink(session: Session, membership: Membership, user: User, at) -> dict:
    row = _current(session, membership, user)
    if row is None:
        raise AppError(404, "not_found", "Привязка не найдена")
    return _revoke(session, row, user, at)


def attach_pending(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    telegram_user_id: int,
    chat_id: int,
    at,
) -> TelegramBinding:
    set_context(session, tenant_id=tenant_id, user_id=user_id)
    pending = session.scalar(
        select(TelegramBinding).where(
            TelegramBinding.tenant_id == tenant_id,
            TelegramBinding.user_id == user_id,
            TelegramBinding.status == "pending",
        )
    )
    if pending is not None:
        pending.status = "revoked"
        pending.revoked_at = at
        session.flush()
    row = TelegramBinding(
        tenant_id=tenant_id,
        user_id=user_id,
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        status="pending",
        linked_at=None,
        revoked_at=None,
        created_at=at,
    )
    session.add(row)
    session.flush()
    return row


def revoke_binding(session: Session, binding: TelegramBinding, at) -> None:
    user = session.get(User, binding.user_id)
    if user is None:
        return
    _revoke(session, binding, user, at)


def subscription_view(session: Session, membership: Membership, user: User) -> dict:
    binding = _by_status(session, membership, user, "active")
    if binding is None:
        raise AppError(404, "not_found", "Активная привязка не найдена")
    row = _subscription(session, binding)
    if row is None:
        raise AppError(404, "not_found", "Подписка не найдена")
    return _subscription_payload(row)


def update_subscription(
    session: Session, membership: Membership, user: User, payload: dict, at
) -> dict:
    binding = _by_status(session, membership, user, "active")
    if binding is None:
        raise AppError(404, "not_found", "Активная привязка не найдена")
    row = _subscription(session, binding)
    if row is None:
        raise AppError(404, "not_found", "Подписка не найдена")
    zone_name = str(payload.get("timezone") or row.timezone)
    if timezone_or_none(zone_name) is None:
        raise AppError(422, "validation_error", "Неизвестная временная зона")
    local = _parse_clock(str(payload.get("local_time") or _format_clock(row.local_time)))
    days = payload.get("days_of_week", row.days_of_week)
    if not isinstance(days, list) or not days or any(item not in range(1, 8) for item in days):
        raise AppError(422, "validation_error", "Некорректные дни недели")
    mode = str(payload.get("mode") or row.mode)
    privacy = str(payload.get("privacy_level") or row.privacy_level)
    if mode not in {"group", "per_company", "both"} or privacy not in {"compact", "full"}:
        raise AppError(422, "validation_error", "Некорректный режим сводки")
    scope = payload.get("company_scope", row.company_scope)
    row.company_scope = _scope(session, membership, scope)
    row.local_time = local
    row.timezone = zone_name
    row.days_of_week = [int(item) for item in days]
    row.mode = mode
    row.privacy_level = privacy
    if "enabled" in payload:
        row.enabled = bool(payload["enabled"])
    if "instant_alerts" in payload:
        row.instant_alerts = bool(payload["instant_alerts"])
    row.quiet_start = _optional_clock(payload.get("quiet_start", row.quiet_start))
    row.quiet_end = _optional_clock(payload.get("quiet_end", row.quiet_end))
    row.updated_at = at
    session.flush()
    return _subscription_payload(row)


def active_binding(session: Session, membership: Membership, user: User) -> TelegramBinding | None:
    return _by_status(session, membership, user, "active")


def _revoke(session: Session, binding: TelegramBinding, user: User, at) -> dict:
    binding.status = "revoked"
    binding.revoked_at = at
    _disable_subscription(session, binding, at)
    _cancel_queue(session, binding, at)
    session.flush()
    _audit(session, user, binding.tenant_id, "telegram_binding_revoked", binding.id, at)
    return _binding_payload(binding)


def _ensure_subscription(session: Session, binding: TelegramBinding, at) -> DigestSubscription:
    found = _subscription(session, binding)
    if found is not None:
        found.enabled = True
        found.updated_at = at
        return found
    row = DigestSubscription(
        tenant_id=binding.tenant_id,
        user_id=binding.user_id,
        binding_id=binding.id,
        company_scope=None,
        local_time=DEFAULT_TIME,
        timezone="Europe/Moscow",
        days_of_week=list(DEFAULT_DAYS),
        mode="group",
        enabled=True,
        instant_alerts=True,
        quiet_start=None,
        quiet_end=None,
        privacy_level="compact",
        last_scheduled_for=None,
        created_at=at,
        updated_at=at,
    )
    session.add(row)
    session.flush()
    return row


def _disable_subscription(session: Session, binding: TelegramBinding, at) -> None:
    row = _subscription(session, binding)
    if row is None:
        return
    row.enabled = False
    row.updated_at = at


def _cancel_queue(session: Session, binding: TelegramBinding, at) -> None:
    rows = session.scalars(
        select(NotificationOutbox).where(
            NotificationOutbox.tenant_id == binding.tenant_id,
            NotificationOutbox.binding_id == binding.id,
            NotificationOutbox.status.in_(("pending", "retry", "sending")),
        )
    ).all()
    for item in rows:
        item.status = "cancelled"
        item.last_error = "revoked"
        item.lease_until = None
        item.next_attempt_at = at


def _scope(session: Session, membership: Membership, raw) -> list[str] | None:
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise AppError(422, "validation_error", "Некорректный список фирм")
    visible = {str(item.id): item for item in companies_for(session, membership)}
    chosen: list[str] = []
    for item in raw:
        key = str(item)
        if key not in visible:
            raise AppError(404, "not_found", "Фирма не найдена")
        chosen.append(key)
    return chosen


def _current(session, membership, user) -> TelegramBinding | None:
    active = _by_status(session, membership, user, "active")
    if active is not None:
        return active
    pending = _by_status(session, membership, user, "pending")
    if pending is not None:
        return pending
    return session.scalar(
        select(TelegramBinding)
        .where(
            TelegramBinding.tenant_id == membership.tenant_id,
            TelegramBinding.user_id == user.id,
            TelegramBinding.status == "revoked",
        )
        .order_by(TelegramBinding.revoked_at.desc())
    )


def _by_status(session, membership, user, status: str) -> TelegramBinding | None:
    return session.scalar(
        select(TelegramBinding).where(
            TelegramBinding.tenant_id == membership.tenant_id,
            TelegramBinding.user_id == user.id,
            TelegramBinding.status == status,
        )
    )


def _subscription(session, binding: TelegramBinding) -> DigestSubscription | None:
    return session.scalar(
        select(DigestSubscription).where(
            DigestSubscription.tenant_id == binding.tenant_id,
            DigestSubscription.binding_id == binding.id,
        )
    )


def _parse_clock(raw: str) -> time:
    try:
        hour, minute = raw.split(":")
        value = time(int(hour), int(minute))
    except (TypeError, ValueError) as exc:
        raise AppError(422, "validation_error", "Некорректное время") from exc
    return value


def _optional_clock(raw) -> time | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, time):
        return raw.replace(second=0, microsecond=0)
    return _parse_clock(str(raw))


def _format_clock(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def _binding_payload(row: TelegramBinding) -> dict:
    linked = None if row.linked_at is None else row.linked_at.isoformat()
    return {"id": str(row.id), "status": row.status, "linked_at": linked}


def _subscription_payload(row: DigestSubscription) -> dict:
    return {
        "id": str(row.id),
        "local_time": _format_clock(row.local_time),
        "timezone": row.timezone,
        "days_of_week": list(row.days_of_week),
        "mode": row.mode,
        "enabled": row.enabled,
        "instant_alerts": row.instant_alerts,
        "quiet_start": None if row.quiet_start is None else _format_clock(row.quiet_start),
        "quiet_end": None if row.quiet_end is None else _format_clock(row.quiet_end),
        "privacy_level": row.privacy_level,
        "company_scope": row.company_scope,
    }


def _audit(session, user, tenant_id, action: str, entity_id, at) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user.id,
            action=action,
            entity_type="telegram_binding",
            entity_id=entity_id,
            before_redacted=None,
            after_redacted=None,
            request_id=None,
            created_at=at,
        )
    )


def load_companies(
    session: Session, membership: Membership, scope: list[str] | None
) -> list[Company]:
    rows = companies_for(session, membership)
    if scope is None:
        return rows
    chosen = set(scope)
    return [item for item in rows if str(item.id) in chosen]


def zone_of(name: str) -> ZoneInfo:
    found = timezone_or_none(name)
    if found is None:
        raise AppError(422, "validation_error", "Неизвестная временная зона")
    return found
