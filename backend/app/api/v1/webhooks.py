import json

from app.api.deps import client_ip, get_db, settings_of
from app.clock import now
from app.errors import AppError
from app.security.rate_limit import enforce
from app.security.tokens import hash_token
from app.services.billing_service import save_webhook
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

router = APIRouter(prefix="/integrations/yookassa", tags=["yookassa"])


@router.post("/webhook")
async def yookassa_webhook(request: Request, session: Session = Depends(get_db)):
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
    try:
        save_webhook(
            session,
            event=str(payload.get("event") or ""),
            payload=payload,
            payload_hash=hash_token(raw.decode("utf-8")),
            at=now(),
        )
    except IntegrityError:
        session.rollback()
    return JSONResponse({"status": "ok"}, status_code=200)
