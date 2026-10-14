import uuid
from datetime import timedelta

from app.clock import now
from app.config import Settings
from app.errors import AppError
from app.models.identity import AuditLog, User, VerificationToken
from app.models.identity import Session as SessionRow
from app.security.passwords import hash_password, verify_password
from app.security.tokens import hash_token, new_secret
from app.services.outbox import build_link, enqueue_email
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

GENERIC_MAIL = "Если адрес указан верно, мы отправили письмо со ссылкой."
INVALID_TOKEN = "Неверный или просроченный токен"


def normalize_email(email: str) -> str:
    return email.strip().lower()


def register_user(
    session: Session,
    settings: Settings,
    *,
    email: str,
    password: str,
    name: str,
) -> None:
    normalized = normalize_email(email)
    existing = session.scalar(select(User).where(User.normalized_email == normalized))
    hash_password(password)
    if existing is not None:
        return
    moment = now()
    user = User(
        email=email.strip(),
        normalized_email=normalized,
        name=name.strip(),
        password_hash=hash_password(password),
        status="active",
        created_at=moment,
    )
    session.add(user)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        return
    _issue_token(
        session,
        settings,
        user=user,
        purpose="verify_email",
        ttl=timedelta(hours=24),
        template_key="verify_email",
        path_prefix="/verify-email",
        moment=moment,
    )
    _audit(session, user.id, None, "register", "user", user.id, moment)


def verify_email(session: Session, token: str) -> None:
    row = _consume_token(session, token, "verify_email")
    user = session.get(User, row.user_id)
    if user is None:
        raise AppError(400, "invalid_token", INVALID_TOKEN)
    user.email_verified_at = now()
    _audit(session, user.id, None, "verify_email", "user", user.id, now())


def login_user(
    session: Session,
    settings: Settings,
    *,
    email: str,
    password: str,
    user_agent: str | None,
) -> tuple[str, str, User]:
    normalized = normalize_email(email)
    user = session.scalar(select(User).where(User.normalized_email == normalized))
    if not verify_password(password, None if user is None else user.password_hash):
        raise AppError(401, "unauthorized", "Неверная почта или пароль")
    if user is None or user.status != "active":
        raise AppError(403, "user_blocked", "Пользователь заблокирован")
    return _open_session(session, settings, user, user_agent)


def logout_user(session: Session, token_hash: str) -> None:
    row = session.scalar(select(SessionRow).where(SessionRow.token_hash == token_hash))
    if row is not None and row.revoked_at is None:
        row.revoked_at = now()


def request_password_reset(session: Session, settings: Settings, email: str) -> None:
    user = session.scalar(
        select(User).where(User.normalized_email == normalize_email(email))
    )
    if user is None or user.status != "active":
        return
    _issue_token(
        session,
        settings,
        user=user,
        purpose="reset_password",
        ttl=timedelta(minutes=30),
        template_key="reset_password",
        path_prefix="/reset-password",
        moment=now(),
    )


def reset_password(session: Session, token: str, password: str) -> None:
    row = _consume_token(session, token, "reset_password")
    user = session.get(User, row.user_id)
    if user is None:
        raise AppError(400, "invalid_token", INVALID_TOKEN)
    moment = now()
    user.password_hash = hash_password(password)
    user.password_changed_at = moment
    session.execute(
        update(SessionRow)
        .where(SessionRow.user_id == user.id, SessionRow.revoked_at.is_(None))
        .values(revoked_at=moment)
    )
    session.execute(
        update(VerificationToken)
        .where(
            VerificationToken.user_id == user.id,
            VerificationToken.purpose == "reset_password",
            VerificationToken.used_at.is_(None),
        )
        .values(used_at=moment)
    )
    enqueue_email(
        session,
        category="auth",
        type_="password_changed",
        to_email=user.email,
        template_key="password_changed",
        payload={"template": "password_changed"},
        idempotency_key=f"password-changed:{user.id}:{moment.isoformat()}",
        created_at=moment,
        user_id=user.id,
    )
    _audit(session, user.id, None, "reset_password", "user", user.id, moment)


def request_email_change(
    session: Session,
    settings: Settings,
    user: User,
    *,
    password: str,
    new_email: str,
) -> None:
    if not verify_password(password, user.password_hash):
        raise AppError(401, "unauthorized", "Неверная почта или пароль")
    normalized = normalize_email(new_email)
    if normalized == user.normalized_email:
        raise AppError(422, "validation_error", "Это уже текущая почта")
    taken = session.scalar(select(User).where(User.normalized_email == normalized))
    if taken is not None:
        raise AppError(409, "conflict", "Адрес уже используется")
    moment = now()
    raw, digest = new_secret()
    session.add(
        VerificationToken(
            user_id=user.id,
            token_hash=digest,
            purpose="change_email",
            expires_at=moment + timedelta(hours=24),
            new_email=normalized,
            created_at=moment,
        )
    )
    link = build_link(settings, f"/verify-email?token={raw}&purpose=change_email")
    enqueue_email(
        session,
        category="auth",
        type_="change_email",
        to_email=new_email.strip(),
        template_key="change_email",
        payload={"link": link},
        idempotency_key=f"change-email:{digest[:16]}",
        created_at=moment,
        user_id=user.id,
    )
    enqueue_email(
        session,
        category="auth",
        type_="email_change_notice",
        to_email=user.email,
        template_key="email_change_notice",
        payload={"template": "email_change_notice"},
        idempotency_key=f"email-change-notice:{digest[:16]}",
        created_at=moment,
        user_id=user.id,
    )


def confirm_email_change(session: Session, token: str) -> None:
    row = _consume_token(session, token, "change_email")
    user = session.get(User, row.user_id)
    if user is None or not row.new_email:
        raise AppError(400, "invalid_token", INVALID_TOKEN)
    taken = session.scalar(select(User).where(User.normalized_email == row.new_email))
    if taken is not None and taken.id != user.id:
        raise AppError(409, "conflict", "Адрес уже используется")
    moment = now()
    user.email = row.new_email
    user.normalized_email = row.new_email
    user.email_verified_at = moment
    enqueue_email(
        session,
        category="auth",
        type_="email_changed",
        to_email=user.email,
        template_key="email_changed",
        payload={"template": "email_changed"},
        idempotency_key=f"email-changed:{row.id}",
        created_at=moment,
        user_id=user.id,
    )


def resend_verification(session: Session, settings: Settings, email: str) -> None:
    user = session.scalar(
        select(User).where(User.normalized_email == normalize_email(email))
    )
    if user is None or user.email_verified_at is not None or user.status != "active":
        return
    _issue_token(
        session,
        settings,
        user=user,
        purpose="verify_email",
        ttl=timedelta(hours=24),
        template_key="verify_email",
        path_prefix="/verify-email",
        moment=now(),
    )


def load_session(
    session: Session, settings: Settings, raw_token: str | None
) -> tuple[SessionRow, User]:
    if not raw_token:
        raise AppError(401, "unauthorized", "Нужна авторизация")
    row = session.scalar(select(SessionRow).where(SessionRow.token_hash == hash_token(raw_token)))
    moment = now()
    if row is None or row.revoked_at is not None or row.expires_at <= moment:
        raise AppError(401, "unauthorized", "Нужна авторизация")
    idle = timedelta(minutes=settings.session_idle_minutes)
    if row.last_seen_at + idle <= moment:
        row.revoked_at = moment
        raise AppError(401, "unauthorized", "Сессия истекла")
    user = session.get(User, row.user_id)
    if user is None or user.status != "active":
        raise AppError(403, "user_blocked", "Пользователь заблокирован")
    row.last_seen_at = moment
    return row, user


def list_sessions(session: Session, user_id: uuid.UUID) -> list[SessionRow]:
    return list(
        session.scalars(
            select(SessionRow)
            .where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
            .order_by(SessionRow.created_at.desc())
        ).all()
    )


def revoke_session(session: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    row = session.scalar(
        select(SessionRow).where(SessionRow.id == session_id, SessionRow.user_id == user_id)
    )
    if row is None:
        raise AppError(404, "not_found", "Сессия не найдена")
    if row.revoked_at is None:
        row.revoked_at = now()


def _open_session(
    session: Session,
    settings: Settings,
    user: User,
    user_agent: str | None,
) -> tuple[str, str, User]:
    moment = now()
    raw, digest = new_secret()
    csrf, _ = new_secret()
    session.add(
        SessionRow(
            user_id=user.id,
            token_hash=digest,
            csrf_secret=csrf,
            created_at=moment,
            last_seen_at=moment,
            expires_at=moment + timedelta(hours=settings.session_absolute_hours),
            user_agent=(user_agent or "")[:256] or None,
        )
    )
    session.flush()
    return raw, csrf, user


def _issue_token(
    session: Session,
    settings: Settings,
    *,
    user: User,
    purpose: str,
    ttl: timedelta,
    template_key: str,
    path_prefix: str,
    moment,
) -> None:
    raw, digest = new_secret()
    session.add(
        VerificationToken(
            user_id=user.id,
            token_hash=digest,
            purpose=purpose,
            expires_at=moment + ttl,
            created_at=moment,
        )
    )
    link = build_link(settings, f"{path_prefix}?token={raw}")
    enqueue_email(
        session,
        category="auth",
        type_=purpose,
        to_email=user.email,
        template_key=template_key,
        payload={"link": link},
        idempotency_key=f"{purpose}:{digest[:16]}",
        created_at=moment,
        user_id=user.id,
    )


def _consume_token(session: Session, token: str, purpose: str) -> VerificationToken:
    row = session.scalar(
        select(VerificationToken)
        .where(
            VerificationToken.token_hash == hash_token(token),
            VerificationToken.purpose == purpose,
        )
        .with_for_update()
    )
    moment = now()
    if row is None or row.used_at is not None or row.expires_at <= moment:
        raise AppError(400, "invalid_token", INVALID_TOKEN)
    row.used_at = moment
    return row


def _audit(
    session: Session,
    user_id: uuid.UUID | None,
    tenant_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: uuid.UUID | None,
    moment,
) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            created_at=moment,
        )
    )
