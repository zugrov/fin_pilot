import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class CashCategory(Base):
    __tablename__ = "cash_categories"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    cash_flow_section: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str] = mapped_column(String(8))
    exclude_from_operating_metrics: Mapped[bool] = mapped_column(Boolean, default=False)


class Wallet(Base):
    __tablename__ = "wallets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"))
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(32))
    masked_identifier: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    availability_type: Mapped[str] = mapped_column(String(16))
    available_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    minimum_reserve: Mapped[Decimal] = mapped_column(Numeric(20, 2), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WalletAccess(Base):
    __tablename__ = "wallet_access"

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    wallet_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    can_create: Mapped[bool] = mapped_column(Boolean, default=False)
    can_read: Mapped[bool] = mapped_column(Boolean, default=True)


class OpeningBalance(Base):
    __tablename__ = "opening_balances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    wallet_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("wallets.id"))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TransferGroup(Base):
    __tablename__ = "transfer_groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"))
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    pairing_method: Mapped[str] = mapped_column(String(32))
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    currency: Mapped[str] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CashTransaction(Base):
    __tablename__ = "cash_transactions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"))
    wallet_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("wallets.id"))
    business_date: Mapped[date] = mapped_column(Date)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    direction: Mapped[str] = mapped_column(String(8))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    description: Mapped[str] = mapped_column(Text, default="")
    document_number: Mapped[str | None] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    classification_origin: Mapped[str] = mapped_column(String(16), default="none")
    locked_classification: Mapped[bool] = mapped_column(Boolean, default=False)
    transfer_group_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TransactionRevision(Base):
    __tablename__ = "transaction_revisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("cash_transactions.id"))
    version: Mapped[int] = mapped_column(Integer)
    previous: Mapped[dict] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
