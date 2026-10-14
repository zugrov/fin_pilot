from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import AppError
from app.integrations.email import EmailMessage
from app.models.identity import Company, User
from app.security.access import assert_finance_access, require_membership
from app.security.context import set_context
from app.services.outbox import enqueue_email


def assert_financial_job(
    session: Session,
    *,
    user_id: UUID,
    tenant_id: UUID,
    company_id: UUID,
    at: datetime,
    grace_days: int,
    bypass: bool,
    mode: str = "write",
) -> None:
    set_context(session, tenant_id=tenant_id, user_id=user_id)
    membership = require_membership(session, user_id, tenant_id)
    company = session.get(Company, company_id)
    if company is None or company.tenant_id != tenant_id:
        raise AppError(404, "not_found", "Фирма не найдена")
    user = session.get(User, user_id)
    verified = user is not None and user.email_verified_at is not None
    assert_finance_access(
        session,
        membership=membership,
        company=company,
        user_verified=verified,
        at=at,
        mode=mode,
        grace_days=grace_days,
        bypass=bypass,
    )


def enqueue_financial_notice(
    session: Session,
    *,
    user: User,
    tenant_id: UUID,
    company_id: UUID,
    at: datetime,
    grace_days: int,
    bypass: bool,
) -> None:
    assert_financial_job(
        session,
        user_id=user.id,
        tenant_id=tenant_id,
        company_id=company_id,
        at=at,
        grace_days=grace_days,
        bypass=bypass,
        mode="send",
    )
    enqueue_email(
        session,
        category="financial",
        type_="digest",
        to_email=user.email,
        template_key="digest",
        payload={"company_id": str(company_id)},
        idempotency_key=f"digest:{company_id}:{at.isoformat()}",
        created_at=at,
        tenant_id=tenant_id,
        user_id=user.id,
        company_id=company_id,
    )


def dispatch_outbox(session: Session, settings: Settings, provider, at: datetime) -> None:
    if settings.app_env == "production" and settings.email_provider_mode == "mock":
        raise RuntimeError("mock email запрещён в production")
    rows = session.execute(text("SELECT * FROM app_pending_outbox()")).mappings().all()
    for row in rows:
        if row["category"] == "financial":
            try:
                assert_financial_job(
                    session,
                    user_id=row["user_id"],
                    tenant_id=row["tenant_id"],
                    company_id=row["company_id"],
                    at=at,
                    grace_days=settings.billing_grace_days,
                    bypass=settings.billing_bypass_allowed(),
                    mode="send",
                )
            except AppError:
                session.execute(
                    text("SELECT app_mark_outbox(:id, 'cancelled', 'access')"),
                    {"id": row["id"]},
                )
                continue
        if not settings.send_real_email:
            if settings.email_provider_mode == "mock" and settings.app_env != "production":
                provider.send(
                    EmailMessage(row["to_email"], row["template_key"], row["payload_redacted"])
                )
                session.execute(
                    text("SELECT app_mark_outbox(:id, 'sent', NULL)"),
                    {"id": row["id"]},
                )
            continue
        provider.send(EmailMessage(row["to_email"], row["template_key"], row["payload_redacted"]))
        session.execute(text("SELECT app_mark_outbox(:id, 'sent', NULL)"), {"id": row["id"]})
