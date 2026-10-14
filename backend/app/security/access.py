from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models.billing import CompanyEntitlement, Subscription
from app.models.identity import Company, CompanyAccess, Membership
from app.security.context import set_context

OWNER = "owner"
FINANCE_MANAGER = "finance_manager"
ACCOUNTANT = "accountant"
VIEWER = "viewer"
OPERATOR = "operator"
BILLING_MANAGER = "billing_manager"

FINANCE_READ = {OWNER, FINANCE_MANAGER, ACCOUNTANT, VIEWER}
FINANCE_WRITE = {OWNER, FINANCE_MANAGER, ACCOUNTANT}
BILLING_ROLES = {OWNER, BILLING_MANAGER}
INVITE_ROLES = {OWNER}


def require_membership(session: Session, user_id: UUID, tenant_id: UUID) -> Membership:
    set_context(session, tenant_id=None, user_id=user_id)
    membership = session.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
        )
    )
    if membership is None:
        raise AppError(404, "not_found", "Пространство не найдено")
    set_context(session, tenant_id=tenant_id, user_id=user_id)
    return membership


def effective_role(membership: Membership, access: CompanyAccess | None) -> str:
    if access is not None and access.role_override:
        return access.role_override
    return membership.role


def companies_for(session: Session, membership: Membership) -> list[Company]:
    companies = list(
        session.scalars(select(Company).where(Company.tenant_id == membership.tenant_id)).all()
    )
    if membership.role == OWNER:
        return companies
    allowed = set(
        session.scalars(
            select(CompanyAccess.company_id).where(
                CompanyAccess.tenant_id == membership.tenant_id,
                CompanyAccess.user_id == membership.user_id,
            )
        ).all()
    )
    return [company for company in companies if company.id in allowed]


def access_row(session: Session, membership: Membership, company_id: UUID) -> CompanyAccess | None:
    return session.scalar(
        select(CompanyAccess).where(
            CompanyAccess.tenant_id == membership.tenant_id,
            CompanyAccess.user_id == membership.user_id,
            CompanyAccess.company_id == company_id,
        )
    )


def can_read_finance(membership: Membership, access: CompanyAccess | None) -> bool:
    if membership.role == OWNER:
        return True
    if access is None:
        return False
    return effective_role(membership, access) in FINANCE_READ


def can_write_finance(membership: Membership, access: CompanyAccess | None) -> bool:
    if membership.role == OWNER:
        return True
    if access is None:
        return False
    return effective_role(membership, access) in FINANCE_WRITE


def assert_billing_role(membership: Membership) -> None:
    if membership.role not in BILLING_ROLES:
        raise AppError(403, "forbidden", "Недостаточно прав для оплаты")


def load_company(session: Session, membership: Membership, company_id: UUID) -> Company:
    company = session.scalar(
        select(Company).where(Company.id == company_id, Company.tenant_id == membership.tenant_id)
    )
    if company is None:
        raise AppError(404, "not_found", "Фирма не найдена")
    visible = {item.id for item in companies_for(session, membership)}
    if company.id not in visible and membership.role != BILLING_MANAGER:
        raise AppError(404, "not_found", "Фирма не найдена")
    if membership.role == BILLING_MANAGER:
        return company
    if company.id not in visible:
        raise AppError(404, "not_found", "Фирма не найдена")
    return company


def find_company_across_memberships(
    session: Session, user_id: UUID, company_id: UUID
) -> tuple[Membership, Company]:
    set_context(session, tenant_id=None, user_id=user_id)
    memberships = list(
        session.scalars(
            select(Membership).where(Membership.user_id == user_id, Membership.status == "active")
        ).all()
    )
    for membership in memberships:
        set_context(session, tenant_id=membership.tenant_id, user_id=user_id)
        company = session.scalar(
            select(Company).where(
                Company.id == company_id,
                Company.tenant_id == membership.tenant_id,
            )
        )
        if company is None:
            continue
        if membership.role == OWNER or membership.role == BILLING_MANAGER:
            return membership, company
        if access_row(session, membership, company.id) is not None:
            return membership, company
    raise AppError(404, "not_found", "Фирма не найдена")


def _entitlement_covers(entitlement, paid_through, at, grace_days: int, mode: str) -> bool:
    if entitlement is None or paid_through is None:
        return False
    if at < entitlement.active_until:
        return True
    grace_end = paid_through + timedelta(days=grace_days)
    return (
        mode == "read"
        and entitlement.active_until == paid_through
        and paid_through <= at < grace_end
    )


def paid_through_state(
    *,
    paid_through: datetime | None,
    at: datetime,
    grace_days: int,
    mode: str,
    entitled: bool,
) -> str:
    if paid_through is None or not entitled:
        raise AppError(402, "payment_required", "Нет оплаченного доступа к фирме")
    grace_end = paid_through + timedelta(days=grace_days)
    if at < paid_through:
        return "ok"
    if mode in {"write", "send"}:
        raise AppError(402, "payment_required", "Оплаченный период закончился")
    if mode == "read" and at < grace_end:
        return "grace_read"
    raise AppError(402, "payment_required", "Оплаченный период закончился")


def assert_finance_access(
    session: Session,
    *,
    membership: Membership,
    company: Company,
    user_verified: bool,
    at: datetime,
    mode: str,
    grace_days: int,
    bypass: bool,
) -> None:
    if not user_verified:
        raise AppError(403, "email_not_verified", "Подтвердите почту")
    access = access_row(session, membership, company.id)
    if mode == "read" and not can_read_finance(membership, access):
        raise AppError(403, "forbidden", "Недостаточно прав")
    if mode in {"write", "send"} and not can_write_finance(membership, access):
        raise AppError(403, "forbidden", "Недостаточно прав")
    if bypass:
        return
    subscription = session.scalar(
        select(Subscription).where(Subscription.tenant_id == membership.tenant_id)
    )
    entitlement = session.scalar(
        select(CompanyEntitlement)
        .where(
            CompanyEntitlement.company_id == company.id,
            CompanyEntitlement.status == "active",
            CompanyEntitlement.active_from <= at,
        )
        .order_by(CompanyEntitlement.active_until.desc())
    )
    entitled = _entitlement_covers(
        entitlement,
        None if subscription is None else subscription.paid_through,
        at,
        grace_days,
        mode,
    )
    paid_through_state(
        paid_through=None if subscription is None else subscription.paid_through,
        at=at,
        grace_days=grace_days,
        mode=mode,
        entitled=entitled,
    )
