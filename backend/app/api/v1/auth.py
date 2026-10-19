from uuid import UUID

from app.api.deps import (
    DbSession,
    clear_session_cookie,
    current_session,
    limit,
    require_csrf,
    set_session_cookie,
    settings_of,
)
from app.services.auth_service import (
    GENERIC_MAIL,
    confirm_email_change,
    list_sessions,
    login_user,
    logout_user,
    register_user,
    request_email_change,
    request_password_reset,
    resend_verification,
    reset_password,
    revoke_session,
    verify_email,
)
from app.services.tenant_service import accept_invitation
from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, EmailStr, Field

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)
    name: str = Field(min_length=1, max_length=200)


class EmailIn(BaseModel):
    email: EmailStr


class TokenIn(BaseModel):
    token: str = Field(min_length=10, max_length=500)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class ResetIn(BaseModel):
    token: str = Field(min_length=10, max_length=500)
    password: str = Field(min_length=12, max_length=200)


class ChangeEmailIn(BaseModel):
    password: str = Field(min_length=1, max_length=200)
    new_email: EmailStr


def _user_payload(user) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "name": user.name,
        "email_verified": user.email_verified_at is not None,
    }


@router.post("/register")
def register(payload: RegisterIn, request: Request, session: DbSession) -> dict:
    limit(request, "register", 5, 3600)
    register_user(
        session,
        settings_of(request),
        email=str(payload.email),
        password=payload.password,
        name=payload.name,
    )
    return {"status": "ok", "message": GENERIC_MAIL}


@router.post("/verify-email")
def verify(payload: TokenIn, session: DbSession) -> dict:
    verify_email(session, payload.token)
    return {"status": "ok"}


@router.post("/resend-verification")
def resend(payload: EmailIn, request: Request, session: DbSession) -> dict:
    limit(request, "resend", 3, 3600)
    resend_verification(session, settings_of(request), str(payload.email))
    return {"status": "ok", "message": GENERIC_MAIL}


@router.post("/login")
def login(
    payload: LoginIn, request: Request, response: Response, session: DbSession
):
    limit(request, "login", 10, 900)
    raw, csrf, user = login_user(
        session,
        settings_of(request),
        email=str(payload.email),
        password=payload.password,
        user_agent=request.headers.get("user-agent"),
    )
    set_session_cookie(response, settings_of(request), raw)
    return {"csrf_token": csrf, "user": _user_payload(user)}


@router.post("/logout")
def logout(request: Request, response: Response, session: DbSession) -> dict:
    row, _user = current_session(request, session)
    require_csrf(request, row)
    raw = request.cookies.get(settings_of(request).session_cookie_name)
    from app.security.tokens import hash_token

    if raw:
        logout_user(session, hash_token(raw))
    clear_session_cookie(response, settings_of(request))
    return {"status": "ok"}


@router.post("/forgot-password")
def forgot(payload: EmailIn, request: Request, session: DbSession) -> dict:
    limit(request, "forgot", 5, 3600)
    request_password_reset(session, settings_of(request), str(payload.email))
    return {"status": "ok", "message": GENERIC_MAIL}


@router.post("/reset-password")
def reset(payload: ResetIn, session: DbSession) -> dict:
    reset_password(session, payload.token, payload.password)
    return {"status": "ok"}


@router.post("/change-email-request")
def change_email(
    payload: ChangeEmailIn, request: Request, session: DbSession
) -> dict:
    row, user = current_session(request, session)
    require_csrf(request, row)
    request_email_change(
        session,
        settings_of(request),
        user,
        password=payload.password,
        new_email=str(payload.new_email),
    )
    return {"status": "ok", "message": GENERIC_MAIL}


@router.post("/change-email-confirm")
def change_email_confirm(payload: TokenIn, session: DbSession) -> dict:
    confirm_email_change(session, payload.token)
    return {"status": "ok"}


@router.get("/me")
def me(request: Request, session: DbSession) -> dict:
    row, user = current_session(request, session)
    from app.models.identity import Membership
    from app.security.context import set_context
    from sqlalchemy import select

    set_context(session, tenant_id=None, user_id=user.id)

    memberships = session.scalars(
        select(Membership).where(Membership.user_id == user.id, Membership.status == "active")
    ).all()
    return {
        "csrf_token": row.csrf_secret,
        "user": _user_payload(user),
        "memberships": [
            {"tenant_id": str(item.tenant_id), "role": item.role} for item in memberships
        ],
    }


@router.get("/sessions")
def sessions(request: Request, session: DbSession) -> dict:
    row, user = current_session(request, session)
    return {
        "sessions": [
            {
                "id": str(item.id),
                "created_at": item.created_at.isoformat(),
                "last_seen_at": item.last_seen_at.isoformat(),
                "current": item.id == row.id,
            }
            for item in list_sessions(session, user.id)
        ]
    }


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: UUID, request: Request, session: DbSession
) -> dict:
    row, user = current_session(request, session)
    require_csrf(request, row)
    revoke_session(session, user.id, session_id)
    return {"status": "ok"}


@router.post("/invitations/accept")
def accept(payload: TokenIn, request: Request, session: DbSession) -> dict:
    _row, user = current_session(request, session)
    require_csrf(request, _row)
    tenant_id = accept_invitation(session, user, payload.token)
    return {"status": "ok", "tenant_id": str(tenant_id)}
