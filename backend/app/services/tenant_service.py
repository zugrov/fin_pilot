import uuid
from datetime import timedelta

from app.clock import now
from app.config import Settings
from app.errors import AppError
from app.models.billing import BillingAccount, Subscription, TariffVersion
from app.models.identity import Company, CompanyAccess, Invitation, Membership, User
from app.security.access import INVITE_ROLES, OWNER
from app.security.context import set_context
from app.security.tokens import new_secret
from app.services.auth_service import normalize_email
from app.services.outbox import build_link, enqueue_email
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

TARIFF_CODE = "beta"


def create_workspace(session: Session, user: User, name: str, timezone_name: str) -> uuid.UUID:
    tariff = session.scalar(
        select(TariffVersion)
        .where(TariffVersion.status == "active")
        .order_by(TariffVersion.valid_from.desc())
    )
    if tariff is None:
        raise AppError(500, "config", "Тариф не загружен")
    moment = now()
    tenant_id = uuid.uuid4()
    set_context(session, tenant_id=tenant_id, user_id=user.id)
    from app.models.identity import Tenant

    session.add(
        Tenant(
            id=tenant_id,
            name=name.strip(),
            default_timezone=timezone_name,
            is_live=False,
            created_at=moment,
        )
    )
    session.flush()
    session.add(
        Membership(
            tenant_id=tenant_id,
            user_id=user.id,
            role=OWNER,
            status="active",
            created_at=moment,
        )
    )
    session.add(
        Subscription(
            tenant_id=tenant_id,
            tariff_version_id=tariff.id,
            status="awaiting_payment",
            company_limit=0,
            timezone=timezone_name,
            auto_renew=False,
            is_renewal_cancelled=False,
            revision=0,
            created_at=moment,
            updated_at=moment,
        )
    )
    session.add(BillingAccount(tenant_id=tenant_id, billing_email=user.email))
    session.execute(
        text("SELECT seed_cash_categories(:tenant_id)"),
        {"tenant_id": tenant_id},
    )
    session.flush()
    return tenant_id


def create_company(
    session: Session,
    membership: Membership,
    *,
    name: str,
    legal_name: str | None,
    inn: str | None,
    kind: str,
) -> Company:
    if membership.role != OWNER:
        raise AppError(403, "forbidden", "Создавать фирмы может владелец")
    moment = now()
    company = Company(
        tenant_id=membership.tenant_id,
        name=name.strip(),
        legal_name=legal_name,
        inn=inn or None,
        kind=kind,
        currency="RUB",
        timezone="Europe/Moscow",
        status="draft",
        created_at=moment,
        updated_at=moment,
    )
    session.add(company)
    try:
        session.flush()
    except IntegrityError:
        session.rollback()
        raise AppError(409, "conflict", "ИНН уже используется в этом пространстве") from None
    return company


def update_company(
    session: Session,
    company: Company,
    *,
    name: str | None,
    legal_name: str | None,
    min_cash_reserve,
    can_write_finance: bool,
) -> Company:
    if name is not None:
        company.name = name.strip()
    if legal_name is not None:
        company.legal_name = legal_name
    if min_cash_reserve is not None:
        if not can_write_finance:
            raise AppError(402, "payment_required", "Оплаченный период закончился")
        company.min_cash_reserve = min_cash_reserve
    company.updated_at = now()
    return company


def invite_member(
    session: Session,
    settings: Settings,
    membership: Membership,
    user: User,
    *,
    email: str,
    role: str,
) -> None:
    if membership.role not in INVITE_ROLES:
        raise AppError(403, "forbidden", "Приглашать может владелец")
    if role not in {"finance_manager", "accountant", "viewer", "operator", "billing_manager"}:
        raise AppError(422, "validation_error", "Неизвестная роль")
    moment = now()
    raw, digest = new_secret()
    normalized = normalize_email(email)
    session.add(
        Invitation(
            tenant_id=membership.tenant_id,
            email=email.strip(),
            normalized_email=normalized,
            role=role,
            token_hash=digest,
            expires_at=moment + timedelta(hours=48),
            invited_by=user.id,
            status="pending",
            created_at=moment,
        )
    )
    link = build_link(settings, f"/accept-invite?token={raw}")
    enqueue_email(
        session,
        category="auth",
        type_="invite",
        to_email=email.strip(),
        template_key="invite",
        payload={"link": link},
        idempotency_key=f"invite:{digest[:16]}",
        created_at=moment,
        tenant_id=membership.tenant_id,
        user_id=user.id,
    )


def accept_invitation(session: Session, user: User, token: str) -> uuid.UUID:
    from app.security.tokens import hash_token
    from sqlalchemy import text

    found = session.execute(
        text("SELECT id, tenant_id FROM app_invitation_context(:digest)"),
        {"digest": hash_token(token)},
    ).mappings().first()
    if found is None:
        raise AppError(400, "invalid_token", "Приглашение недействительно")
    set_context(session, tenant_id=found["tenant_id"], user_id=user.id)
    invitation = session.scalar(select(Invitation).where(Invitation.id == found["id"]))
    moment = now()
    if (
        invitation is None
        or invitation.used_at is not None
        or invitation.expires_at <= moment
        or invitation.normalized_email != user.normalized_email
    ):
        raise AppError(400, "invalid_token", "Приглашение недействительно")
    existing = session.scalar(
        select(Membership).where(
            Membership.tenant_id == invitation.tenant_id,
            Membership.user_id == user.id,
        )
    )
    if existing is None:
        session.add(
            Membership(
                tenant_id=invitation.tenant_id,
                user_id=user.id,
                role=invitation.role,
                status="active",
                created_at=moment,
            )
        )
    invitation.used_at = moment
    invitation.status = "accepted"
    session.flush()
    return invitation.tenant_id


def grant_company_access(
    session: Session,
    membership: Membership,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
) -> None:
    if membership.role != OWNER:
        raise AppError(403, "forbidden", "Недостаточно прав")
    session.add(
        CompanyAccess(
            tenant_id=membership.tenant_id,
            user_id=user_id,
            company_id=company_id,
        )
    )
    session.flush()

