import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OrganizationProfileVersion(Base):
    """
    Версия профиля организации (P1b).
    Черновик (confirmed_at IS NULL) редактируется; после подтверждения — неизменяем.
    """

    __tablename__ = "organization_profile_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id"), nullable=False)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    org_form: Mapped[str] = mapped_column(String(32), nullable=False, default="unspecified")
    tax_system: Mapped[str] = mapped_column(String(32), nullable=False, default="unspecified")
    usn_tax_object: Mapped[str] = mapped_column(String(32), nullable=False, default="unspecified")
    vat_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    vat_regime_detail: Mapped[str | None] = mapped_column(String(32), nullable=True)
    vat_default_rate: Mapped[str | None] = mapped_column(String(8), nullable=True)
    prices_include_vat: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    vat_exemption_article_145: Mapped[bool | None] = mapped_column(nullable=True)
    is_new_organization: Mapped[bool | None] = mapped_column(nullable=True)
    revenue_recognition_method: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown"
    )
    accounting_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unspecified"
    )
    industry_sphere: Mapped[str] = mapped_column(String(32), nullable=False, default="unspecified")
    money_channels: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    prior_year_revenue_band: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown"
    )
    month_close_policy: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    confirmed_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
