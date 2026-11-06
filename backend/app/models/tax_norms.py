import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TaxNormVersion(Base):
    """
    Общая версия справочника налоговых норм (не привязана к организации).
    Наполнение — миграции/seed; публичных write-эндпоинтов нет.
    """

    __tablename__ = "tax_norm_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    usn_vat_exemption_threshold_rub: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    special_rate_base_5_cap_base_rub: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4), nullable=True
    )
    special_rate_base_7_cap_base_rub: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4), nullable=True
    )
    special_rates_deflator: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    vat_rates_general: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    vat_rates_special: Mapped[list | None] = mapped_column(JSONB, nullable=True)
