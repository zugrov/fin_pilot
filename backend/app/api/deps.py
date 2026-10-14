import secrets
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.models.identity import Membership, User
from app.models.identity import Session as SessionRow
from app.security.access import require_membership
from app.security.rate_limit import enforce
from app.services.auth_service import load_session


def get_db(request: Request):
    session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def settings_of(request: Request) -> Settings:
    return request.app.state.settings


def client_ip(request: Request, settings: Settings) -> str:
    peer = request.client.host if request.client else ""
    if settings.trust_proxy and peer in {"127.0.0.1", "::1"}:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return peer


def limit(request: Request, action: str, max_hits: int, window: int) -> None:
    settings = settings_of(request)
    enforce(request.app.state.limiter, f"{action}:{client_ip(request, settings)}", max_hits, window)


def current_session(request: Request, session: Session) -> tuple[SessionRow, User]:
    settings = settings_of(request)
    raw = request.cookies.get(settings.session_cookie_name)
    return load_session(session, settings, raw)


def require_csrf(request: Request, row) -> None:
    header = request.headers.get("x-csrf-token") or ""
    secret = row.csrf_secret
    if len(header) != len(secret) or not secrets.compare_digest(header, secret):
        raise AppError(403, "csrf", "Неверный CSRF-токен")


def tenant_of(request: Request, session: Session, user: User) -> Membership:
    raw = request.headers.get("x-tenant-id")
    if not raw:
        raise AppError(400, "validation_error", "Нужен заголовок X-Tenant-Id")
    try:
        tenant_id = UUID(raw)
    except ValueError as exc:
        raise AppError(400, "validation_error", "Некорректный идентификатор пространства") from exc
    return require_membership(session, user.id, tenant_id)


def set_session_cookie(response, settings: Settings, raw_token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=raw_token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
        max_age=settings.session_absolute_hours * 3600,
    )


def clear_session_cookie(response, settings: Settings) -> None:
    response.delete_cookie(settings.session_cookie_name, path="/")
