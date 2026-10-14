import hmac
from uuid import UUID

from app.api.deps import current_session, get_db, require_csrf, settings_of, tenant_of
from app.clock import now
from app.errors import AppError
from app.services import telegram_binding, telegram_bot, telegram_digest
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

router = APIRouter(tags=["telegram"])


class SubscriptionIn(BaseModel):
    local_time: str | None = None
    timezone: str | None = None
    days_of_week: list[int] | None = None
    mode: str | None = None
    enabled: bool | None = None
    instant_alerts: bool | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None
    privacy_level: str | None = None
    company_scope: list[UUID] | None = None


def _actor(request: Request, session: Session, *, mutate: bool):
    row, user = current_session(request, session)
    if mutate:
        require_csrf(request, row)
    membership = tenant_of(request, session, user)
    return user, membership


@router.post("/telegram/link-token")
def post_link_token(request: Request, session: Session = Depends(get_db)):
    user, membership = _actor(request, session, mutate=True)
    return telegram_binding.issue_token(session, membership, user, settings_of(request), now())


@router.get("/telegram/binding")
def get_binding(request: Request, session: Session = Depends(get_db)):
    user, membership = _actor(request, session, mutate=False)
    return telegram_binding.binding_view(session, membership, user)


@router.post("/telegram/binding/confirm")
def post_confirm(request: Request, session: Session = Depends(get_db)):
    user, membership = _actor(request, session, mutate=True)
    return telegram_binding.confirm_binding(session, membership, user, now())


@router.delete("/telegram/binding")
def delete_binding(request: Request, session: Session = Depends(get_db)):
    user, membership = _actor(request, session, mutate=True)
    return telegram_binding.unlink(session, membership, user, now())


@router.get("/telegram/subscription")
def get_subscription(request: Request, session: Session = Depends(get_db)):
    user, membership = _actor(request, session, mutate=False)
    return telegram_binding.subscription_view(session, membership, user)


@router.put("/telegram/subscription")
def put_subscription(
    payload: SubscriptionIn, request: Request, session: Session = Depends(get_db)
):
    user, membership = _actor(request, session, mutate=True)
    data = payload.model_dump(exclude_unset=True)
    if "company_scope" in data and data["company_scope"] is not None:
        data["company_scope"] = [str(item) for item in data["company_scope"]]
    return telegram_binding.update_subscription(session, membership, user, data, now())


@router.post("/telegram/digest-preview")
def post_preview(request: Request, session: Session = Depends(get_db)):
    user, membership = _actor(request, session, mutate=True)
    return telegram_digest.preview_text(session, membership, user, settings_of(request), now())


@router.post("/telegram/send-test")
def post_send_test(request: Request, session: Session = Depends(get_db)):
    user, membership = _actor(request, session, mutate=True)
    snapshot = telegram_digest.queue_manual(
        session,
        membership,
        user,
        settings_of(request),
        request_id=f"send-test:{now().isoformat()}",
        at=now(),
    )
    return {"status": "queued", "sent": False, "snapshot_id": str(snapshot.id)}


@router.post("/integrations/telegram/webhook")
def post_webhook(payload: dict, request: Request, session: Session = Depends(get_db)):
    settings = settings_of(request)
    secret = settings.telegram_webhook_secret
    if not secret:
        raise AppError(404, "not_found", "Webhook Telegram выключен")
    header = request.headers.get("x-telegram-bot-api-secret-token") or ""
    if len(header) != len(secret) or not hmac.compare_digest(header, secret):
        raise AppError(403, "forbidden", "Неверный секрет webhook")
    telegram_bot.ingest_update(session, settings, payload, now())
    return {"status": "saved"}
