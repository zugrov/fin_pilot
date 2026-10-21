"""Сервис gate допуска письма к preview (FA-R04.1).

Не подключён к legacy IMAP/poll и не создаёт side effects в БД.
"""

from __future__ import annotations

from datetime import datetime

from app.config import Settings
from app.domain.mail_admission import (
    MailAdmissionContext,
    MailAdmissionDecision,
    MailAdmissionOutcome,
    PolicyStop,
    TrustedServerBinding,
    TrustedTransportAuth,
    UntrustedMailEnvelope,
    apply_mail_admission_policy,
    reject_sender_identity_mismatch,
)
from app.errors import AppError
from app.models.identity import Company, User
from app.models.imports import SourceConnection
from app.security.access import assert_finance_access, require_membership
from app.security.context import set_context
from app.services.auth_service import normalize_email
from sqlalchemy import select
from sqlalchemy.orm import Session


def evaluate_mail_admission(
    session: Session,
    settings: Settings,
    *,
    envelope: UntrustedMailEnvelope,
    transport: TrustedTransportAuth | None,
    binding: TrustedServerBinding,
    at: datetime,
) -> MailAdmissionDecision:
    set_context(session, tenant_id=binding.tenant_id, user_id=binding.actor_user_id)

    actor = session.get(User, binding.actor_user_id)
    if actor is None or actor.status != "active":
        return MailAdmissionDecision(
            outcome=MailAdmissionOutcome.REJECT,
            reason_code="user_inactive",
            context=None,
        )

    actor_email = normalize_email(actor.normalized_email)
    policy = apply_mail_admission_policy(envelope, transport)
    if isinstance(policy, PolicyStop):
        return policy.decision

    sender_normalized = policy.sender_normalized
    if actor.email_verified_at is None:
        return MailAdmissionDecision(
            outcome=MailAdmissionOutcome.REJECT,
            reason_code="email_not_verified",
            context=None,
        )

    if sender_normalized != actor_email:
        other = session.scalar(
            select(User).where(
                User.normalized_email == sender_normalized,
                User.status == "active",
            )
        )
        if other is not None and other.id != actor.id:
            return MailAdmissionDecision(
                outcome=MailAdmissionOutcome.REVIEW,
                reason_code="routing_ambiguous",
                context=None,
            )
        identity_stop = reject_sender_identity_mismatch(sender_normalized, actor_email)
        assert identity_stop is not None
        return identity_stop.decision

    connection = session.get(SourceConnection, binding.connection_id)
    if connection is None:
        return MailAdmissionDecision(
            outcome=MailAdmissionOutcome.REJECT,
            reason_code="source_not_found",
            context=None,
        )
    if connection.type != "email":
        return MailAdmissionDecision(
            outcome=MailAdmissionOutcome.REJECT,
            reason_code="source_type_mismatch",
            context=None,
        )
    if (
        connection.tenant_id != binding.tenant_id
        or connection.company_id != binding.company_id
    ):
        return MailAdmissionDecision(
            outcome=MailAdmissionOutcome.REJECT,
            reason_code="routing_binding_conflict",
            context=None,
        )

    company = session.get(Company, binding.company_id)
    if company is None or company.tenant_id != binding.tenant_id:
        return MailAdmissionDecision(
            outcome=MailAdmissionOutcome.REJECT,
            reason_code="routing_binding_conflict",
            context=None,
        )

    try:
        membership = require_membership(session, binding.actor_user_id, binding.tenant_id)
        assert_finance_access(
            session,
            membership=membership,
            company=company,
            user_verified=True,
            at=at,
            mode="write",
            grace_days=settings.billing_grace_days,
            bypass=settings.billing_bypass_allowed(),
        )
    except AppError as exc:
        return MailAdmissionDecision(
            outcome=MailAdmissionOutcome.REJECT,
            reason_code=str(exc.code),
            context=None,
        )

    return MailAdmissionDecision(
        outcome=MailAdmissionOutcome.ALLOW_PREVIEW,
        reason_code="ok",
        context=MailAdmissionContext(
            tenant_id=binding.tenant_id,
            company_id=binding.company_id,
            connection_id=binding.connection_id,
            actor_user_id=binding.actor_user_id,
            sender_normalized=sender_normalized,
        ),
    )
