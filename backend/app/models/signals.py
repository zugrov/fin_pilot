import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, Integer, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class BudgetVersion(Base):
    __tablename__ = "budget_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(200))
    year: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    basis: Mapped[str] = mapped_column(String(16))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BudgetLine(Base):
    __tablename__ = "budget_lines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    budget_version_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    month: Mapped[int] = mapped_column(Integer)
    category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    direction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    metric_type: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    distribution_method: Mapped[str] = mapped_column(String(32))


class BudgetDailyAllocation(Base):
    __tablename__ = "budget_daily_allocations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    line_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    allocation_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))


class AlertRule(Base):
    __tablename__ = "alert_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    rule_type: Mapped[str] = mapped_column(String(32))
    thresholds_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    severity: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    cooldown_minutes: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    rule_type: Mapped[str] = mapped_column(String(32))
    fingerprint: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    evidence_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    source_refs: Mapped[list[Any]] = mapped_column(JSONB)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
