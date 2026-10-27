import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.api.v1 import (
    auth,
    billing,
    classification_packs,
    companies,
    imports,
    ingestions,
    mail_quarantine,
    plan,
    revenue,
    rules,
    signals,
    telegram,
    transactions,
    wallets,
    webhooks,
)
from app.clock import reset_clock, set_clock
from app.config import Settings, get_settings
from app.errors import AppError
from app.integrations.payments import build_payment_provider
from app.security.rate_limit import build_rate_limiter


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Финансовый автопилот", version="0.2.0")
    app.state.settings = settings
    from app.clock import SystemClock

    app.state.clock = SystemClock()
    app.state.engine = create_engine(settings.database_url, pool_pre_ping=True)
    app.state.worker_engine = create_engine(settings.worker_database_url, pool_pre_ping=True)
    app.state.session_factory = sessionmaker(
        bind=app.state.engine, autoflush=False, expire_on_commit=False
    )
    app.state.worker_session_factory = sessionmaker(
        bind=app.state.worker_engine, autoflush=False, expire_on_commit=False
    )
    app.state.limiter = build_rate_limiter(settings)
    app.state.payment_provider_factory = lambda: build_payment_provider(settings)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "details": exc.details,
                "request_id": getattr(request.state, "request_id", ""),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={
                "code": "validation_error",
                "message": "Проверьте поля запроса",
                "details": {"errors": exc.errors()},
                "request_id": getattr(request.state, "request_id", ""),
            },
        )

    @app.get("/health/live")
    def live() -> dict:
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready(request: Request) -> dict:
        session = request.app.state.session_factory()
        try:
            session.execute(text("SELECT 1"))
            session.commit()
        finally:
            session.close()
        return {"status": "ok"}

    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(companies.router, prefix="/api/v1")
    app.include_router(wallets.router, prefix="/api/v1")
    app.include_router(transactions.router, prefix="/api/v1")
    app.include_router(imports.router, prefix="/api/v1")
    app.include_router(ingestions.router, prefix="/api/v1")
    app.include_router(mail_quarantine.router, prefix="/api/v1")
    app.include_router(revenue.router, prefix="/api/v1")
    app.include_router(plan.router, prefix="/api/v1")
    app.include_router(signals.router, prefix="/api/v1")
    app.include_router(telegram.router, prefix="/api/v1")
    app.include_router(rules.router, prefix="/api/v1")
    app.include_router(classification_packs.router, prefix="/api/v1")
    app.include_router(billing.router, prefix="/api/v1")
    app.include_router(webhooks.router, prefix="/api/v1")
    return app


class RequestContextMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid.uuid4())
        state = scope.setdefault("state", {})
        state["request_id"] = request_id
        clock = scope["app"].state.clock
        token = set_clock(clock)

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers") or [])
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            reset_clock(token)


app = create_app()
