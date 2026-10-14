import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class RecurrenceRule(Base):
    __tablename__ = "recurrence_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    frequency: Mapped[str] = mapped_column(String(16))
    interval_count: Mapped[int] = mapped_column(Integer)
    day_of_month: Mapped[int | None] = mapped_column(Integer)
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    month_end_policy: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str] = mapped_column(String(8))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    currency: Mapped[str] = mapped_column(String(3))
    confidence: Mapped[str] = mapped_column(String(16))
    priority: Mapped[str] = mapped_column(String(16))
    category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    wallet_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PlannedCashEvent(Base):
    __tablename__ = "planned_cash_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    wallet_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    direction: Mapped[str] = mapped_column(String(8))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    currency: Mapped[str] = mapped_column(String(3), default="RUB")
    category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    due_date: Mapped[date] = mapped_column(Date)
    expected_date: Mapped[date] = mapped_column(Date)
    confidence: Mapped[str] = mapped_column(String(16))
    priority: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    recurrence_rule_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    occurrence_key: Mapped[str | None] = mapped_column(String(80))
    notes: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str | None] = mapped_column(String(128))
    source_connection_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PaymentMatch(Base):
    __tablename__ = "payment_matches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    cash_transaction_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Obligation(Base):
    __tablename__ = "obligations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    obligation_type: Mapped[str] = mapped_column(String(16))
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    document_ref: Mapped[str | None] = mapped_column(Text)
    issue_date: Mapped[date] = mapped_column(Date)
    due_date: Mapped[date] = mapped_column(Date)
    original_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    status: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ObligationCashLink(Base):
    __tablename__ = "obligation_cash_links"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    obligation_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ForecastRun(Base):
    __tablename__ = "forecast_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    as_of: Mapped[date] = mapped_column(Date)
    scenario: Mapped[str] = mapped_column(String(16))
    horizon_days: Mapped[int] = mapped_column(Integer)
    input_revision: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    quality_flags: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    opening_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    gap_date: Mapped[date | None] = mapped_column(Date)
    gap_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ForecastPoint(Base):
    __tablename__ = "forecast_points"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    point_date: Mapped[date] = mapped_column(Date)
    opening_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    inflows: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    outflows: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    closing_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))


class ForecastContribution(Base):
    __tablename__ = "forecast_contributions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    point_date: Mapped[date] = mapped_column(Date)
    source_type: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    direction: Mapped[str] = mapped_column(String(8))
    assumption: Mapped[str] = mapped_column(String(32))
