import json
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.config import Settings
from app.domain.billing.periods import renewal_bounds
from app.domain.billing.pricing import discount_factor
from app.domain.billing.receipts import build_package_lines, build_upgrade_line
from app.domain.billing.upgrade import prorate, upgrade_amount
from app.domain.money import money, money_str
from app.errors import AppError
from app.integrations.payments import DisabledPaymentProvider, amount_of
from app.models.billing import (
    AnnualOfferVersion,
    BillingAccount,
    BillingActivation,
    BillingAudit,
    BillingPeriod,
    BillingQuote,
    BillingWebhookInbox,
    CompanyEntitlement,
    Invoice,
    InvoiceLine,
    PaymentAttempt,
    Refund,
    Subscription,
    TariffVersion,
)
from app.models.identity import Company, IdempotencyRecord, Tenant, User
from app.security.access import assert_billing_role
from app.security.context import set_context
from app.security.tokens import canonical_hash
from app.services.outbox import enqueue_email
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

MIN_CHARGE = Decimal("1.00")


def tariff_view(session: Session, at: datetime) -> dict:
    tariff = _tariff(session)
    offer = _offer(session, at)
    examples = []
    for count in range(1, 6):
        monthly = _monthly(tariff, count)
        listed = money(monthly * 12)
        discount = offer.discount_percent if offer is not None else Decimal("0")
        payable = money(listed * discount_factor(discount))
        examples.append(
            {
                "companies": count,
                "monthly": money_str(monthly),
                "annual_list": money_str(listed),
                "annual_payable": money_str(payable),
                "savings": money_str(money(listed - payable)),
                "monthly_equivalent": money_str(money(payable / Decimal(12))),
            }
        )
    return {
        "code": tariff.code,
        "version": tariff.version,
        "currency": tariff.currency,
        "monthly_first_company_price": money_str(tariff.monthly_first_company_price),
        "monthly_additional_price": money_str(tariff.monthly_additional_price),
        "annual_discount_percent": money_str(offer.discount_percent) if offer else None,
        "annual_offer_status": offer.status if offer else None,
        "annual_billing_enabled": offer is not None and offer.status == "approved",
        "tax_config_version": tariff.tax_config_version,
        "examples": examples,
    }


def create_quote(
    session: Session,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    companies: int,
    interval: str,
    keep_company_ids: list[uuid.UUID] | None,
    at: datetime,
) -> BillingQuote:
    if interval == "year" and not settings.annual_billing_enabled:
        raise AppError(422, "annual_disabled", "Годовая оплата выключена")
    subscription = _subscription(session, tenant_id)
    tariff = _tariff(session)
    offer = _offer(session, at)
    if interval == "year" and (offer is None or offer.status != "approved"):
        raise AppError(422, "offer_missing", "Нет утверждённой годовой скидки")
    period = _covering(session, subscription.id, at)
    same_interval = interval == (subscription.current_interval or interval)
    if (
        period is not None
        and subscription.paid_through is not None
        and at < subscription.paid_through
        and same_interval
        and companies > subscription.company_limit
    ):
        return _upgrade_quote(
            session, subscription, period, tariff, companies, interval, at, settings
        )
    if companies < subscription.company_limit:
        if not keep_company_ids or len(set(keep_company_ids)) != companies:
            raise AppError(422, "choose_companies", "Выберите фирмы, которые остаются")
    kind = "initial"
    if subscription.paid_through is not None and at < subscription.paid_through:
        kind = "renewal"
    discount = offer.discount_percent if interval == "year" and offer is not None else Decimal("0")
    listed, discount_amount, payable = _package(tariff, companies, interval, discount)
    period_start, period_end = _quoted_window(subscription, interval, kind, at)
    quote = BillingQuote(
        tenant_id=tenant_id,
        subscription_id=subscription.id,
        kind=kind,
        interval=interval,
        as_of=at,
        expires_at=at + timedelta(minutes=settings.quote_ttl_minutes),
        expected_revision=subscription.revision,
        base_company_limit=subscription.company_limit,
        target_company_limit=companies,
        list_amount=listed,
        discount_amount=discount_amount,
        payable_amount=payable,
        discount_percent=discount,
        offer_version_id=None if offer is None or interval == "month" else offer.id,
        period_start=period_start,
        period_end=period_end,
        calculation_json={
            "companies": companies,
            "interval": interval,
            "keep_company_ids": [str(item) for item in (keep_company_ids or [])],
            "source": "tariff_version",
        },
        status="open",
        created_at=at,
    )
    session.add(quote)
    session.flush()
    return quote


def quote_payload(quote: BillingQuote) -> dict:
    return {
        "id": str(quote.id),
        "kind": quote.kind,
        "interval": quote.interval,
        "companies": quote.target_company_limit,
        "list_amount": money_str(quote.list_amount),
        "discount_amount": money_str(quote.discount_amount),
        "payable_amount": money_str(quote.payable_amount),
        "discount_percent": money_str(quote.discount_percent),
        "period_start": _iso(quote.period_start),
        "period_end": _iso(quote.period_end),
        "expires_at": _iso(quote.expires_at),
        "status": quote.status,
        "currency": "RUB",
    }


def checkout(
    session: Session,
    settings: Settings,
    provider,
    *,
    user: User,
    tenant_id: uuid.UUID,
    quote_id: uuid.UUID,
    offer_accepted: bool,
    idempotency_key: str,
    at: datetime,
) -> tuple[int, dict]:
    if user.email_verified_at is None:
        raise AppError(403, "email_not_verified", "Подтвердите почту")
    from app.models.identity import Membership

    membership = session.scalar(
        select(Membership).where(
            Membership.user_id == user.id,
            Membership.tenant_id == tenant_id,
            Membership.status == "active",
        )
    )
    if membership is None:
        raise AppError(404, "not_found", "Пространство не найдено")
    assert_billing_role(membership)
    if not offer_accepted:
        raise AppError(422, "offer_required", "Нужно принять оферту")
    request_hash = canonical_hash(
        json.dumps(
            {"offer_accepted": True, "quote_id": str(quote_id)},
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.scope == "checkout",
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise AppError(409, "idempotency_conflict", "Ключ уже использован с другим запросом")
        if existing.payment_attempt_id is not None:
            attempt = session.get(PaymentAttempt, existing.payment_attempt_id)
            if attempt is not None and attempt.status == "unknown":
                body = _retry_unknown(session, provider, attempt, at)
                return 200, body
        return existing.status_code, existing.response_body

    quote = session.scalar(
        select(BillingQuote).where(
            BillingQuote.id == quote_id,
            BillingQuote.tenant_id == tenant_id,
        )
    )
    if quote is None:
        raise AppError(404, "not_found", "Расчёт не найден")
    if quote.status != "open":
        raise AppError(409, "conflict", "Расчёт уже использован")
    if quote.expires_at <= at:
        quote.status = "expired"
        raise AppError(422, "quote_expired", "Срок расчёта истёк")
    if quote.payable_amount < MIN_CHARGE:
        raise AppError(422, "charge_too_small", "Сумма меньше 1 RUB, оформите следующий период")
    subscription = _lock(session, quote.subscription_id)
    if subscription.revision != quote.expected_revision:
        raise AppError(409, "stale_revision", "Подписка изменилась, запросите расчёт заново")
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise AppError(404, "not_found", "Пространство не найдено")
    _assert_channel(settings, tenant, provider)
    invoice, attempt, _body = _open_attempt(session, settings, quote, subscription, user, at)
    try:
        remote = provider.create_payment(attempt.idempotence_key, attempt.request_body)
    except TimeoutError:
        attempt.status = "unknown"
        attempt.provider_error = "timeout"
        payload = {
            "status": "unknown",
            "payment_id": str(attempt.id),
            "activated": False,
        }
        _remember(
            session, user, tenant_id, idempotency_key, request_hash, 202, payload, attempt, at
        )
        return 202, payload
    attempt.provider_payment_id = remote["id"]
    attempt.confirmation_url = (remote.get("confirmation") or {}).get("confirmation_url")
    attempt.status = "pending" if remote.get("status") == "pending" else str(remote.get("status"))
    attempt.test_mode = bool(remote.get("test"))
    quote.status = "consumed"
    invoice.status = "pending"
    account = session.scalar(select(BillingAccount).where(BillingAccount.tenant_id == tenant_id))
    if account is not None:
        account.offer_version = "beta-2026-10-14"
        account.offer_accepted_at = at
        if not account.billing_email:
            account.billing_email = user.email
    payload = {
        "status": attempt.status,
        "payment_id": str(attempt.id),
        "confirmation_url": attempt.confirmation_url,
        "activated": False,
        "invoice_id": str(invoice.id),
        "payable_amount": money_str(invoice.payable_amount),
    }
    _remember(session, user, tenant_id, idempotency_key, request_hash, 200, payload, attempt, at)
    return 200, payload


def payment_view(session: Session, tenant_id: uuid.UUID, attempt_id: uuid.UUID) -> dict:
    attempt = session.scalar(
        select(PaymentAttempt).where(
            PaymentAttempt.id == attempt_id,
            PaymentAttempt.tenant_id == tenant_id,
        )
    )
    if attempt is None:
        raise AppError(404, "not_found", "Платёж не найден")
    invoice = session.get(Invoice, attempt.invoice_id)
    activation = None
    if invoice is not None:
        activation = session.scalar(
            select(BillingActivation).where(BillingActivation.invoice_id == invoice.id)
        )
    return {
        "id": str(attempt.id),
        "status": attempt.status,
        "activated": activation is not None,
        "confirmation_url": attempt.confirmation_url,
        "amount": money_str(attempt.amount),
        "currency": attempt.currency,
    }


def apply_remote_payment(session: Session, settings: Settings, remote: dict, at: datetime) -> dict:
    provider_id = str(remote.get("id") or "")
    ctx = session.execute(
        text("SELECT * FROM app_payment_context(:pid)"),
        {"pid": provider_id},
    ).mappings().first()
    if ctx is None:
        return {"activated": False, "reason": "unknown_payment"}
    set_context(session, tenant_id=ctx["tenant_id"], user_id=None)
    attempt = session.scalar(
        select(PaymentAttempt).where(PaymentAttempt.id == ctx["attempt_id"]).with_for_update()
    )
    if attempt is None:
        return {"activated": False, "reason": "unknown_payment"}
    invoice = session.scalar(
        select(Invoice).where(Invoice.id == attempt.invoice_id).with_for_update()
    )
    if invoice is None:
        return {"activated": False, "reason": "unknown_payment"}
    subscription = _lock(session, invoice.subscription_id)
    tenant = session.get(Tenant, invoice.tenant_id)
    existing = session.scalar(
        select(BillingActivation).where(BillingActivation.invoice_id == invoice.id)
    )
    if existing is not None:
        return {"activated": True, "replay": True, "activation_id": str(existing.id)}
    status = str(remote.get("status") or "")
    if status in {"pending", "waiting_for_capture"}:
        attempt.status = status
        return {"activated": False, "reason": status}
    if status == "canceled":
        attempt.status = "canceled"
        if invoice.status == "pending":
            invoice.status = "cancelled"
        return {"activated": False, "reason": "canceled"}
    if status != "succeeded":
        attempt.status = "unknown"
        return {"activated": False, "reason": "not_succeeded"}
    if tenant is None:
        return {"activated": False, "reason": "unknown_payment"}
    problem = _verification_problem(remote, invoice, settings, tenant)
    if problem:
        attempt.status = "unknown"
        attempt.provider_error = problem
        invoice.status = "manual_review"
        _billing_audit(session, invoice.tenant_id, "verification_rejected", invoice.id, problem, at)
        return {"activated": False, "reason": problem}
    quote = session.get(BillingQuote, invoice.quote_id)
    if quote is None:
        invoice.status = "manual_review"
        return {"activated": False, "reason": "quote_missing"}
    if subscription.revision != quote.expected_revision:
        attempt.status = "unknown"
        attempt.provider_error = "stale_revision"
        invoice.status = "manual_review"
        return {"activated": False, "reason": "stale_revision"}
    if quote.kind == "upgrade":
        period = _covering(session, subscription.id, at)
        if (
            period is None
            or at >= period.end_at
            or subscription.company_limit != quote.base_company_limit
        ):
            attempt.status = "unknown"
            attempt.provider_error = "late_upgrade"
            invoice.status = "manual_review"
            return {"activated": False, "reason": "late_upgrade"}
    try:
        with session.begin_nested():
            activation = _grant(session, subscription, invoice, quote, remote, at)
            session.add(activation)
            session.flush()
    except IntegrityError:
        existing = session.scalar(
            select(BillingActivation).where(BillingActivation.invoice_id == invoice.id)
        )
        if existing is not None:
            return {"activated": True, "replay": True, "activation_id": str(existing.id)}
        attempt.status = "unknown"
        attempt.provider_error = "conflict"
        invoice.status = "manual_review"
        return {"activated": False, "reason": "conflict"}
    _enqueue_payment_mail(session, invoice, at)
    return {"activated": True, "replay": False, "activation_id": str(activation.id)}


def process_inbox(session: Session, provider, settings: Settings, at: datetime) -> int:
    rows = list(
        session.scalars(
            select(BillingWebhookInbox)
            .where(BillingWebhookInbox.status == "received")
            .order_by(BillingWebhookInbox.received_at)
        ).all()
    )
    done = 0
    for row in rows:
        try:
            with session.begin_nested():
                remote = provider.get_payment(row.object_id)
                outcome = apply_remote_payment(session, settings, remote, at)
            row.status = "ignored" if outcome.get("reason") == "unknown_payment" else "processed"
            done += 1
        except Exception as exc:
            row.status = "failed"
            row.attempts += 1
            row.last_error = str(exc)[:400]
    return done


def reconcile_open_payments(session: Session, provider, settings: Settings, at: datetime) -> int:
    rows = session.execute(text("SELECT * FROM app_open_payments()")).mappings().all()
    changed = 0
    for row in rows:
        set_context(session, tenant_id=row["tenant_id"], user_id=None)
        attempt = session.scalar(
            select(PaymentAttempt).where(PaymentAttempt.id == row["attempt_id"]).with_for_update()
        )
        if attempt is None:
            continue
        attempt.reconcile_attempts += 1
        if attempt.provider_payment_id:
            remote = provider.get_payment(attempt.provider_payment_id)
        else:
            if attempt.reconcile_attempts > 5:
                invoice = session.get(Invoice, attempt.invoice_id)
                if invoice is not None and invoice.status == "pending":
                    invoice.status = "manual_review"
                continue
            remote = provider.create_payment(attempt.idempotence_key, attempt.request_body)
            attempt.provider_payment_id = remote["id"]
            session.flush()
        apply_remote_payment(session, settings, remote, at)
        changed += 1
    return changed


def activate_company(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    at: datetime,
) -> CompanyEntitlement:
    subscription = _lock(session, _subscription(session, tenant_id).id)
    company = session.scalar(
        select(Company).where(Company.id == company_id, Company.tenant_id == tenant_id)
    )
    if company is None or company.status == "archived":
        raise AppError(404, "not_found", "Фирма не найдена")
    period = _covering(session, subscription.id, at)
    if period is None:
        raise AppError(402, "payment_required", "Нет оплаченного периода")
    existing = session.scalar(
        select(CompanyEntitlement).where(
            CompanyEntitlement.company_id == company.id,
            CompanyEntitlement.status == "active",
            CompanyEntitlement.active_from <= at,
            CompanyEntitlement.active_until > at,
        )
    )
    if existing is not None:
        return existing
    active_count = len(
        list(
            session.scalars(
                select(CompanyEntitlement).where(
                    CompanyEntitlement.subscription_id == subscription.id,
                    CompanyEntitlement.status == "active",
                    CompanyEntitlement.active_from <= at,
                    CompanyEntitlement.active_until > at,
                )
            ).all()
        )
    )
    if active_count >= period.company_limit:
        raise AppError(402, "payment_required", "Нет свободного оплаченного слота")
    entitlement = CompanyEntitlement(
        tenant_id=tenant_id,
        subscription_id=subscription.id,
        company_id=company.id,
        active_from=at,
        active_until=period.end_at,
        status="active",
        period_id=period.id,
    )
    session.add(entitlement)
    company.status = "active"
    company.updated_at = at
    session.flush()
    return entitlement


def schedule_change(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    interval: str | None,
    companies: int | None,
    keep_company_ids: list[uuid.UUID] | None,
    at: datetime,
) -> Subscription:
    subscription = _lock(session, _subscription(session, tenant_id).id)
    if interval is not None:
        if interval not in {"month", "year"}:
            raise AppError(422, "validation_error", "Неизвестный интервал")
        if subscription.current_interval and interval != subscription.current_interval:
            subscription.scheduled_interval = interval
    if companies is not None:
        if companies < 1:
            raise AppError(422, "validation_error", "Нужна хотя бы одна фирма")
        if companies > subscription.company_limit:
            raise AppError(
                422, "upgrade_requires_payment", "Увеличение числа фирм оформляется доплатой"
            )
        if companies < subscription.company_limit:
            if not keep_company_ids or len(set(keep_company_ids)) != companies:
                raise AppError(422, "choose_companies", "Выберите фирмы, которые остаются")
            subscription.scheduled_company_limit = companies
            subscription.scheduled_keep_company_ids = [str(item) for item in keep_company_ids]
        else:
            subscription.scheduled_company_limit = companies
    subscription.revision += 1
    subscription.updated_at = at
    return subscription


def cancel_renewal(session: Session, tenant_id: uuid.UUID, at: datetime) -> Subscription:
    subscription = _lock(session, _subscription(session, tenant_id).id)
    subscription.is_renewal_cancelled = True
    subscription.auto_renew = False
    subscription.updated_at = at
    return subscription


def subscription_view(
    session: Session, tenant_id: uuid.UUID, at: datetime, grace_days: int
) -> dict:
    subscription = _subscription(session, tenant_id)
    periods = list(
        session.scalars(
            select(BillingPeriod)
            .where(BillingPeriod.subscription_id == subscription.id)
            .order_by(BillingPeriod.start_at)
        ).all()
    )
    current = _covering(session, subscription.id, at)
    future = [item for item in periods if item.start_at > at and item.status != "revoked"]
    return {
        "status": _display_status(subscription, at, grace_days),
        "company_limit": (
            current.company_limit if current is not None else subscription.company_limit
        ),
        "stored_company_limit": subscription.company_limit,
        "current_interval": subscription.current_interval,
        "scheduled_interval": subscription.scheduled_interval,
        "scheduled_company_limit": subscription.scheduled_company_limit,
        "paid_through": _iso(subscription.paid_through),
        "is_renewal_cancelled": subscription.is_renewal_cancelled,
        "auto_renew": subscription.auto_renew,
        "revision": subscription.revision,
        "current_period": None if current is None else _period_payload(current),
        "future_periods": [_period_payload(item) for item in future],
    }


def list_invoices(session: Session, tenant_id: uuid.UUID) -> list[dict]:
    rows = session.scalars(
        select(Invoice).where(Invoice.tenant_id == tenant_id).order_by(Invoice.created_at.desc())
    ).all()
    return [
        {
            "id": str(row.id),
            "number": row.number,
            "status": row.status,
            "interval": row.billing_interval,
            "payable_amount": money_str(row.payable_amount),
            "currency": row.currency,
            "paid_at": _iso(row.paid_at),
        }
        for row in rows
    ]


def save_webhook(
    session: Session, *, event: str, payload: dict, payload_hash: str, at: datetime
) -> bool:
    obj = payload.get("object") or {}
    object_id = str(obj.get("id") or "")
    if not event or not object_id:
        raise AppError(400, "validation_error", "Некорректное уведомление")
    existing = session.scalar(
        select(BillingWebhookInbox).where(
            BillingWebhookInbox.provider == "yookassa",
            BillingWebhookInbox.object_id == object_id,
            BillingWebhookInbox.event == event,
            BillingWebhookInbox.payload_hash == payload_hash,
        )
    )
    if existing is not None:
        return False
    session.add(
        BillingWebhookInbox(
            provider="yookassa",
            object_id=object_id,
            event=event,
            payload_hash=payload_hash,
            payload_redacted=payload,
            received_at=at,
            status="received",
            attempts=0,
        )
    )
    session.flush()
    return True


def enqueue_renewal_reminders(session: Session, settings: Settings, at: datetime) -> int:
    rows = session.execute(text("SELECT * FROM app_subscriptions_for_reminders()")).mappings().all()
    created = 0
    for row in rows:
        if row["is_renewal_cancelled"] or row["paid_through"] is None:
            continue
        zone = ZoneInfo("Europe/Moscow")
        days = (row["paid_through"].astimezone(zone).date() - at.astimezone(zone).date()).days
        interval = row["current_interval"] or "month"
        targets = (
            settings.annual_reminder_days if interval == "year" else settings.monthly_reminder_days
        )
        if days not in targets:
            continue
        set_context(session, tenant_id=row["tenant_id"], user_id=None)
        account = session.scalar(
            select(BillingAccount).where(BillingAccount.tenant_id == row["tenant_id"])
        )
        if account is None or not account.billing_email:
            continue
        enqueue_email(
            session,
            category="billing",
            type_="renewal_reminder",
            to_email=account.billing_email,
            template_key="renewal_reminder",
            payload={"days": days, "interval": interval},
            idempotency_key=f"reminder:{row['id']}:{days}:{row['paid_through'].date().isoformat()}",
            created_at=at,
            tenant_id=row["tenant_id"],
        )
        created += 1
    return created


def apply_verified_refund(
    session: Session,
    settings: Settings,
    *,
    tenant_id: uuid.UUID,
    payment_attempt_id: uuid.UUID,
    remote: dict,
    reason: str,
    actor: str,
    at: datetime,
) -> Refund:
    if not settings.refunds_enabled:
        raise AppError(403, "refunds_disabled", "Возвраты выключены")
    attempt = session.scalar(
        select(PaymentAttempt).where(
            PaymentAttempt.id == payment_attempt_id,
            PaymentAttempt.tenant_id == tenant_id,
        )
    )
    if attempt is None:
        raise AppError(404, "not_found", "Платёж не найден")
    if str(remote.get("status")) != "succeeded":
        raise AppError(409, "conflict", "Возврат у провайдера не подтверждён")
    amount = amount_of(remote)
    subscription = _lock(session, _subscription(session, tenant_id).id)
    refund = Refund(
        tenant_id=tenant_id,
        payment_attempt_id=attempt.id,
        provider_refund_id=str(remote.get("id") or ""),
        amount=amount,
        status="succeeded" if amount == attempt.amount else "manual_review",
        idempotence_key=str(uuid.uuid4()),
        reason=reason,
        created_by=None,
        verified_at=at if amount == attempt.amount else None,
        created_at=at,
    )
    session.add(refund)
    if amount != attempt.amount:
        _billing_audit(session, tenant_id, "refund_manual_review", attempt.id, actor, at)
        session.flush()
        return refund
    activation = session.scalar(
        select(BillingActivation).where(BillingActivation.invoice_id == attempt.invoice_id)
    )
    if activation is not None and activation.period_id is not None:
        period = session.get(BillingPeriod, activation.period_id)
        if period is not None and period.status != "revoked":
            period.status = "revoked"
            previous = session.scalar(
                select(BillingPeriod).where(
                    BillingPeriod.subscription_id == subscription.id,
                    BillingPeriod.status != "revoked",
                    BillingPeriod.end_at == period.start_at,
                )
            )
            new_end = previous.end_at if previous is not None else period.start_at
            subscription.paid_through = new_end
            subscription.company_limit = 0 if previous is None else previous.company_limit
            subscription.status = "active" if previous is not None and new_end > at else "expired"
            for entitlement in session.scalars(
                select(CompanyEntitlement).where(
                    CompanyEntitlement.subscription_id == subscription.id,
                    CompanyEntitlement.status == "active",
                )
            ):
                if previous is None:
                    entitlement.status = "ended"
                    entitlement.active_until = min(entitlement.active_until, at)
                elif entitlement.active_until > previous.end_at:
                    entitlement.active_until = previous.end_at
    _billing_audit(session, tenant_id, "refund_applied", attempt.id, actor, at)
    session.flush()
    return refund


def _grant(session, subscription, invoice, quote, remote, at: datetime) -> BillingActivation:
    succeeded_at = _succeeded_at(remote, at)
    if quote.kind == "upgrade":
        period = _covering(session, subscription.id, at)
        if period is None:
            raise AppError(409, "conflict", "Нет периода для доплаты")
        period.company_limit = quote.target_company_limit
        subscription.company_limit = quote.target_company_limit
        subscription.revision += 1
        subscription.updated_at = at
        invoice.status = "paid"
        invoice.paid_at = succeeded_at
        _mark_attempt_succeeded(session, invoice, succeeded_at, at)
        return BillingActivation(
            tenant_id=invoice.tenant_id,
            invoice_id=invoice.id,
            subscription_id=subscription.id,
            period_id=period.id,
            change_revision=subscription.revision,
            applied_at=at,
        )
    if quote.period_start is not None and quote.period_end is not None:
        start = quote.period_start
        end = quote.period_end
        anchor = subscription.billing_anchor or start
    else:
        start, end, anchor = renewal_bounds(
            paid_through=subscription.paid_through,
            billing_anchor=subscription.billing_anchor,
            succeeded_at=succeeded_at,
            interval=quote.interval,
            tz=ZoneInfo(subscription.timezone),
        )
    future = start > at
    tariff = _tariff(session)
    period = BillingPeriod(
        tenant_id=invoice.tenant_id,
        subscription_id=subscription.id,
        start_at=start,
        end_at=end,
        interval=quote.interval,
        company_limit=quote.target_company_limit,
        monthly_base_snapshot=_monthly(tariff, quote.target_company_limit),
        discount_percent=quote.discount_percent,
        annual_offer_version_id=quote.offer_version_id,
        paid_amount=invoice.payable_amount,
        status="scheduled" if future else "active",
        activation_invoice_id=invoice.id,
        created_at=at,
    )
    session.add(period)
    session.flush()
    if not future:
        subscription.company_limit = quote.target_company_limit
        subscription.current_interval = quote.interval
        subscription.billing_anchor = anchor
        subscription.status = "active"
    else:
        subscription.scheduled_company_limit = quote.target_company_limit
        subscription.scheduled_interval = quote.interval
    if subscription.paid_through is None or end > subscription.paid_through:
        subscription.paid_through = end
    subscription.revision += 1
    subscription.is_renewal_cancelled = False
    subscription.updated_at = at
    keep = (quote.calculation_json or {}).get("keep_company_ids") or []
    _extend_entitlements(
        session,
        subscription,
        end,
        keep,
        quote.target_company_limit,
        quote.base_company_limit,
    )
    invoice.status = "paid"
    invoice.paid_at = succeeded_at
    _mark_attempt_succeeded(session, invoice, succeeded_at, at)
    _billing_audit(session, invoice.tenant_id, "activated", invoice.id, quote.kind, at)
    return BillingActivation(
        tenant_id=invoice.tenant_id,
        invoice_id=invoice.id,
        subscription_id=subscription.id,
        period_id=period.id,
        change_revision=subscription.revision,
        applied_at=at,
    )


def _extend_entitlements(session, subscription, new_end, keep_ids, target: int, base: int) -> None:
    keep = set(keep_ids)
    for entitlement in session.scalars(
        select(CompanyEntitlement).where(
            CompanyEntitlement.subscription_id == subscription.id,
            CompanyEntitlement.status == "active",
        )
    ):
        if target < base and str(entitlement.company_id) not in keep:
            continue
        if entitlement.active_until < new_end:
            entitlement.active_until = new_end


def _mark_attempt_succeeded(session, invoice, succeeded_at, at: datetime) -> None:
    attempt = session.scalar(
        select(PaymentAttempt)
        .where(PaymentAttempt.invoice_id == invoice.id)
        .order_by(PaymentAttempt.created_at.desc())
    )
    if attempt is not None:
        attempt.status = "succeeded"
        attempt.verified_at = at
        if attempt.test_mode is None:
            attempt.test_mode = False
    _ = succeeded_at


def _open_attempt(session, settings, quote, subscription, user, at: datetime):
    lines = _lines_for(quote)
    if sum((line.amount for line in lines), Decimal("0")) != quote.payable_amount:
        raise AppError(500, "receipt_mismatch", "Сумма строк чека не равна платежу")
    seq = session.execute(text("SELECT nextval('invoice_number_seq')")).scalar_one()
    invoice = Invoice(
        tenant_id=quote.tenant_id,
        subscription_id=subscription.id,
        quote_id=quote.id,
        kind=quote.kind,
        status="draft",
        number=f"FP-{at.astimezone(ZoneInfo('Europe/Moscow')).year}-{int(seq):06d}",
        currency="RUB",
        list_amount=quote.list_amount,
        discount_amount=quote.discount_amount,
        payable_amount=quote.payable_amount,
        pricing_snapshot={
            "companies": quote.target_company_limit,
            "interval": quote.interval,
            "discount_percent": money_str(quote.discount_percent),
            "offer_version_id": (
                None if quote.offer_version_id is None else str(quote.offer_version_id)
            ),
            "vat_rate": None,
        },
        billing_interval=quote.interval,
        intended_period_start=quote.period_start,
        intended_period_end=quote.period_end,
        created_at=at,
    )
    session.add(invoice)
    session.flush()
    for line in lines:
        session.add(
            InvoiceLine(
                tenant_id=quote.tenant_id,
                invoice_id=invoice.id,
                description=line.description,
                quantity=line.quantity,
                discounted_unit_price=line.discounted_unit_price,
                amount=line.amount,
                service_period_start=quote.period_start,
                service_period_end=quote.period_end,
                receipt_attributes={},
            )
        )
    attempt_id = uuid.uuid4()
    body = _provider_body(settings, invoice, quote, user)
    attempt = PaymentAttempt(
        id=attempt_id,
        tenant_id=quote.tenant_id,
        invoice_id=invoice.id,
        provider="yookassa",
        idempotence_key=str(attempt_id),
        request_hash=canonical_hash(json.dumps(body, sort_keys=True)),
        request_body=body,
        amount=quote.payable_amount,
        currency="RUB",
        status="new",
        created_at=at,
        reconcile_attempts=0,
    )
    session.add(attempt)
    session.flush()
    return invoice, attempt, body


def _provider_body(settings: Settings, invoice: Invoice, quote: BillingQuote, user: User) -> dict:
    return_url = settings.yookassa_return_url or (
        settings.public_base_url.rstrip("/") + "/billing/return"
    )
    return {
        "amount": {"value": money_str(invoice.payable_amount), "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": (
            f"Подписка Финансовый автопилот, {quote.interval}, "
            f"{quote.target_company_limit} фирм"
        ),
        "metadata": {
            "invoice_id": str(invoice.id),
            "subscription_id": str(invoice.subscription_id),
            "tenant_id": str(invoice.tenant_id),
            "interval": quote.interval,
        },
        "merchant_customer": user.email,
    }


def _lines_for(quote: BillingQuote):
    if quote.kind == "upgrade":
        added = quote.target_company_limit - quote.base_company_limit
        return build_upgrade_line(
            description=f"Доплата за {added} фирм до конца периода",
            payable=quote.payable_amount,
        )
    return build_package_lines(
        companies=quote.target_company_limit,
        interval=quote.interval,
        payable=quote.payable_amount,
        discount_percent=quote.discount_percent,
    )


def _retry_unknown(session, provider, attempt: PaymentAttempt, at: datetime) -> dict:
    remote = provider.create_payment(attempt.idempotence_key, attempt.request_body)
    attempt.provider_payment_id = remote["id"]
    attempt.confirmation_url = (remote.get("confirmation") or {}).get("confirmation_url")
    attempt.status = "pending"
    attempt.provider_error = None
    _ = at
    return {
        "status": "pending",
        "payment_id": str(attempt.id),
        "confirmation_url": attempt.confirmation_url,
        "activated": False,
    }


def _remember(
    session, user, tenant_id, key, request_hash, status_code, payload, attempt, at
) -> None:
    session.add(
        IdempotencyRecord(
            tenant_id=tenant_id,
            user_id=user.id,
            scope="checkout",
            idempotency_key=key,
            request_hash=request_hash,
            status_code=status_code,
            response_body=payload,
            payment_attempt_id=attempt.id,
            created_at=at,
        )
    )


def _verification_problem(remote, invoice, settings, tenant) -> str | None:
    if amount_of(remote) != invoice.payable_amount or remote["amount"]["currency"] != "RUB":
        return "amount_mismatch"
    if not settings.yookassa_shop_id or remote.get("shop_id") != settings.yookassa_shop_id:
        return "shop_mismatch"
    meta = remote.get("metadata") or {}
    if meta.get("invoice_id") != str(invoice.id) or meta.get("tenant_id") != str(invoice.tenant_id):
        return "metadata_mismatch"
    if meta.get("interval") != invoice.billing_interval:
        return "metadata_mismatch"
    if remote.get("test") is True and (tenant.is_live or settings.billing_mode == "live"):
        return "test_payment_live_tenant"
    return None


def _assert_channel(settings, tenant, provider) -> None:
    live = settings.billing_mode == "live" or tenant.is_live
    if live and (
        not settings.receipt_mode
        or not settings.yookassa_shop_id
        or not settings.yookassa_secret_key
    ):
        raise AppError(
            422,
            "receipt_config_missing",
            "Для боевой оплаты не заданы реквизиты чека и продавца",
        )
    if live and not settings.send_live_payments:
        raise AppError(403, "live_payments_disabled", "Боевые платежи выключены")
    if isinstance(provider, DisabledPaymentProvider):
        raise AppError(503, "billing_integration_disabled", "Платёжная интеграция выключена")


def _upgrade_quote(session, subscription, period, tariff, companies, interval, at, settings):
    added = companies - subscription.company_limit
    remaining = int((period.end_at - at).total_seconds())
    total = int((period.end_at - period.start_at).total_seconds())
    if total <= 0:
        raise AppError(409, "conflict", "Период уже закончился")
    payable = upgrade_amount(
        interval=interval,
        added_slots=added,
        remaining_seconds=max(remaining, 0),
        period_seconds=total,
        discount_percent=period.discount_percent,
    )
    gross_unit = tariff.monthly_additional_price * (12 if interval == "year" else 1)
    listed = (
        prorate(gross_unit, added, max(remaining, 0), total)
        if payable is not None
        else Decimal("0.00")
    )
    status = "open" if payable is not None else "deferred"
    amount = payable if payable is not None else Decimal("0.00")
    quote = BillingQuote(
        tenant_id=subscription.tenant_id,
        subscription_id=subscription.id,
        kind="upgrade",
        interval=interval,
        as_of=at,
        expires_at=at + timedelta(minutes=settings.quote_ttl_minutes),
        expected_revision=subscription.revision,
        base_company_limit=subscription.company_limit,
        target_company_limit=companies,
        list_amount=listed,
        discount_amount=money(listed - amount),
        payable_amount=amount,
        discount_percent=period.discount_percent,
        offer_version_id=period.annual_offer_version_id,
        period_start=period.start_at,
        period_end=period.end_at,
        calculation_json={
            "added_slots": added,
            "remaining_seconds": remaining,
            "period_seconds": total,
        },
        status=status,
        created_at=at,
    )
    session.add(quote)
    session.flush()
    return quote


def _quoted_window(subscription, interval, kind, at):
    if kind != "renewal" or subscription.paid_through is None or at >= subscription.paid_through:
        return None, None
    anchor = subscription.billing_anchor or subscription.paid_through
    zone = ZoneInfo(subscription.timezone)
    end = renewal_bounds(
        paid_through=subscription.paid_through,
        billing_anchor=anchor,
        succeeded_at=at,
        interval=interval,
        tz=zone,
    )[1]
    return subscription.paid_through, end


def _package(tariff, companies: int, interval: str, discount: Decimal):
    monthly = _monthly(tariff, companies)
    if interval == "month":
        return monthly, Decimal("0.00"), monthly
    listed = money(monthly * 12)
    payable = money(listed * discount_factor(discount))
    return listed, money(listed - payable), payable


def _monthly(tariff, companies: int) -> Decimal:
    if companies < 1:
        raise AppError(422, "validation_error", "Нужна хотя бы одна фирма")
    return money(
        tariff.monthly_first_company_price + tariff.monthly_additional_price * (companies - 1)
    )


def _tariff(session: Session) -> TariffVersion:
    tariff = session.scalar(
        select(TariffVersion)
        .where(TariffVersion.status == "active")
        .order_by(TariffVersion.valid_from.desc())
    )
    if tariff is None:
        raise AppError(500, "config", "Тариф не загружен")
    return tariff


def _offer(session: Session, at: datetime) -> AnnualOfferVersion | None:
    return session.scalar(
        select(AnnualOfferVersion)
        .where(AnnualOfferVersion.status == "approved", AnnualOfferVersion.valid_from <= at)
        .order_by(AnnualOfferVersion.valid_from.desc())
    )


def _subscription(session: Session, tenant_id: uuid.UUID) -> Subscription:
    subscription = session.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
    if subscription is None:
        raise AppError(404, "not_found", "Подписка не найдена")
    return subscription


def _lock(session: Session, subscription_id: uuid.UUID) -> Subscription:
    subscription = session.scalar(
        select(Subscription)
        .where(Subscription.id == subscription_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if subscription is None:
        raise AppError(404, "not_found", "Подписка не найдена")
    return subscription


def _covering(session: Session, subscription_id: uuid.UUID, at: datetime) -> BillingPeriod | None:
    return session.scalar(
        select(BillingPeriod).where(
            BillingPeriod.subscription_id == subscription_id,
            BillingPeriod.status != "revoked",
            BillingPeriod.start_at <= at,
            BillingPeriod.end_at > at,
        )
    )


def _enqueue_payment_mail(session, invoice, at: datetime) -> None:
    try:
        with session.begin_nested():
            account = session.scalar(
                select(BillingAccount).where(BillingAccount.tenant_id == invoice.tenant_id)
            )
            if account is None or not account.billing_email:
                return
            enqueue_email(
                session,
                category="billing",
                type_="payment_success",
                to_email=account.billing_email,
                template_key="payment_success",
                payload={"invoice": str(invoice.id), "amount": money_str(invoice.payable_amount)},
                idempotency_key=f"payment-success:{invoice.id}",
                created_at=at,
                tenant_id=invoice.tenant_id,
            )
    except Exception:
        _billing_audit(session, invoice.tenant_id, "email_enqueue_failed", invoice.id, "outbox", at)


def _billing_audit(session, tenant_id, action, entity_id, actor, at: datetime) -> None:
    session.add(
        BillingAudit(
            tenant_id=tenant_id,
            actor=str(actor),
            action=action,
            entity_id=entity_id,
            evidence_redacted={"action": action},
            created_at=at,
        )
    )


def _display_status(subscription: Subscription, at: datetime, grace_days: int) -> str:
    if subscription.paid_through is None:
        return "awaiting_payment"
    if at < subscription.paid_through:
        return "active"
    if at < subscription.paid_through + timedelta(days=grace_days):
        return "grace"
    return "expired"


def _period_payload(period: BillingPeriod) -> dict:
    return {
        "id": str(period.id),
        "start_at": _iso(period.start_at),
        "end_at": _iso(period.end_at),
        "interval": period.interval,
        "company_limit": period.company_limit,
        "discount_percent": money_str(period.discount_percent),
        "paid_amount": money_str(period.paid_amount),
        "status": period.status,
    }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _succeeded_at(remote: dict, fallback: datetime) -> datetime:
    raw = remote.get("captured_at") or remote.get("succeeded_at")
    if not raw:
        return fallback
    return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
