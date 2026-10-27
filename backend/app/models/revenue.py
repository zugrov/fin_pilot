import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Direction(Base):
    __tablename__ = "directions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Counterparty(Base):
    __tablename__ = "counterparties"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    inn: Mapped[str | None] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RevenueEntry(Base):
    __tablename__ = "revenue_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    direction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    recognition_date: Mapped[date] = mapped_column(Date)
    document_number: Mapped[str | None] = mapped_column(Text)
    external_id: Mapped[str | None] = mapped_column(String(128))
    source_connection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    amount_ex_vat: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    vat_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    amount_inc_vat: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    entry_type: Mapped[str] = mapped_column(String(16))
    vat_basis: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    linked_sale_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("revenue_entries.id", ondelete="NO ACTION"),
        nullable=True,
    )


class RevenueCashMatch(Base):
    __tablename__ = "revenue_cash_matches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    revenue_entry_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cash_transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
