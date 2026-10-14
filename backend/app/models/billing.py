import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TariffVersion(Base):
    __tablename__ = "tariff_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    code: Mapped[str] = mapped_column(String(32))
    version: Mapped[int]
    currency: Mapped[str] = mapped_column(String(3))
    monthly_first_company_price: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    monthly_additional_price: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    tax_config_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AnnualOfferVersion(Base):
    __tablename__ = "annual_offer_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tariff_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tariff_versions.id"))
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    status: Mapped[str] = mapped_column(String(16))
    approved_by: Mapped[str] = mapped_column(String(200))
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approval_source: Mapped[str] = mapped_column(String(32))
    offer_terms_version: Mapped[str] = mapped_column(String(64))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingAccount(Base):
    __tablename__ = "billing_accounts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), unique=True)
    payer_type: Mapped[str | None] = mapped_column(String(32))
    payer_name: Mapped[str | None] = mapped_column(String(300))
    inn: Mapped[str | None] = mapped_column(String(12))
    billing_email: Mapped[str | None] = mapped_column(String(320))
    offer_version: Mapped[str | None] = mapped_column(String(64))
    offer_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_versions: Mapped[dict | None] = mapped_column(JSONB)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), unique=True)
    tariff_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tariff_versions.id"))
    status: Mapped[str] = mapped_column(String(32), default="awaiting_payment")
    company_limit: Mapped[int] = mapped_column(default=0)
    current_interval: Mapped[str | None] = mapped_column(String(16))
    scheduled_interval: Mapped[str | None] = mapped_column(String(16))
    paid_through: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    billing_anchor: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    auto_renew: Mapped[bool] = mapped_column(default=False)
    scheduled_company_limit: Mapped[int | None]
    scheduled_keep_company_ids: Mapped[list | None] = mapped_column(JSONB)
    is_renewal_cancelled: Mapped[bool] = mapped_column(default=False)
    revision: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingPeriod(Base):
    __tablename__ = "billing_periods"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    subscription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("subscriptions.id"))
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    interval: Mapped[str] = mapped_column(String(16))
    company_limit: Mapped[int]
    monthly_base_snapshot: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    annual_offer_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    status: Mapped[str] = mapped_column(String(16))
    activation_invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CompanyEntitlement(Base):
    __tablename__ = "company_entitlements"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    subscription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("subscriptions.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"))
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    period_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class BillingQuote(Base):
    __tablename__ = "billing_quotes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    subscription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("subscriptions.id"))
    kind: Mapped[str] = mapped_column(String(16))
    interval: Mapped[str] = mapped_column(String(16))
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expected_revision: Mapped[int]
    base_company_limit: Mapped[int]
    target_company_limit: Mapped[int]
    list_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    payable_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(12, 6))
    offer_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calculation_json: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    subscription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("subscriptions.id"))
    quote_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("billing_quotes.id"))
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    number: Mapped[str] = mapped_column(String(32), unique=True)
    currency: Mapped[str] = mapped_column(String(3))
    list_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    payable_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    pricing_snapshot: Mapped[dict] = mapped_column(JSONB)
    billing_interval: Mapped[str] = mapped_column(String(16))
    intended_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    intended_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("invoices.id"))
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[int]
    discounted_unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    company_refs: Mapped[list | None] = mapped_column(JSONB)
    service_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    service_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receipt_attributes: Mapped[dict] = mapped_column(JSONB)


class PaymentAttempt(Base):
    __tablename__ = "payment_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("invoices.id"))
    provider: Mapped[str] = mapped_column(String(32), default="yookassa")
    provider_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    idempotence_key: Mapped[str] = mapped_column(String(64), unique=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    request_body: Mapped[dict] = mapped_column(JSONB)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(32))
    test_mode: Mapped[bool | None]
    confirmation_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_error: Mapped[str | None] = mapped_column(Text)
    reconcile_attempts: Mapped[int] = mapped_column(default=0)


class BillingWebhookInbox(Base):
    __tablename__ = "billing_webhook_inbox"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32))
    object_id: Mapped[str] = mapped_column(String(64))
    event: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload_redacted: Mapped[dict] = mapped_column(JSONB)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class BillingActivation(Base):
    __tablename__ = "billing_activations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("invoices.id"), unique=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("subscriptions.id"))
    period_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    change_revision: Mapped[int]
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Refund(Base):
    __tablename__ = "refunds"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    payment_attempt_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("payment_attempts.id"))
    provider_refund_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    status: Mapped[str] = mapped_column(String(32))
    idempotence_key: Mapped[str] = mapped_column(String(64), unique=True)
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BillingAudit(Base):
    __tablename__ = "billing_audit"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    evidence_redacted: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
