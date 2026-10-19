import json

from app.api.deps import DbSession, client_ip, settings_of
from app.clock import now
from app.errors import AppError
from app.models.billing import BillingWebhookInbox
from app.security.rate_limit import enforce
from app.security.tokens import hash_token
from app.services.billing_service import save_webhook
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

router = APIRouter(prefix="/integrations/yookassa", tags=["yookassa"])


def _webhook_already_inbox(
    session, *, event: str, object_id: str, payload_hash: str
) -> bool:
    return (
        session.scalar(
            select(BillingWebhookInbox.id).where(
                BillingWebhookInbox.provider == "yookassa",
                BillingWebhookInbox.object_id == object_id,
                BillingWebhookInbox.event == event,
                BillingWebhookInbox.payload_hash == payload_hash,
            )
        )
        is not None
    )


@router.post("/webhook")
async def yookassa_webhook(request: Request, session: DbSession):
    settings = settings_of(request)
    peer = client_ip(request, settings)
    enforce(request.app.state.limiter, f"yookassa:{peer}", settings.webhook_rate_limit, 60)
    if settings.yookassa_ips and peer not in settings.yookassa_ips:
        raise AppError(403, "forbidden", "Источник уведомления не разрешён")
    raw = await request.body()
    if len(raw) > settings.webhook_max_bytes:
        raise AppError(413, "payload_too_large", "Слишком большое уведомление")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AppError(400, "validation_error", "Некорректное уведомление") from exc
    if not isinstance(payload, dict):
        raise AppError(400, "validation_error", "Некорректное уведомление")
    event = str(payload.get("event") or "")
    obj = payload.get("object") or {}
    object_id = str(obj.get("id") or "")
    payload_hash = hash_token(raw.decode("utf-8"))
    try:
        save_webhook(
            session,
            event=event,
            payload=payload,
            payload_hash=payload_hash,
            at=now(),
        )
    except IntegrityError:
        session.rollback()
        if not _webhook_already_inbox(
            session, event=event, object_id=object_id, payload_hash=payload_hash
        ):
            raise
    return JSONResponse({"status": "ok"}, status_code=200)
