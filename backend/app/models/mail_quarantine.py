import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MailQuarantineEntry(Base):
    __tablename__ = "mail_quarantine_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"))
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    channel: Mapped[str] = mapped_column(String(16), default="email")
    uidvalidity: Mapped[int] = mapped_column(BigInteger)
    uid: Mapped[int] = mapped_column(BigInteger)
    message_digest: Mapped[str] = mapped_column(String(64))
    message_id_header: Mapped[str | None] = mapped_column(Text)
    ingress_stage: Mapped[str] = mapped_column(String(16))
    reason_code: Mapped[str] = mapped_column(String(64))
    admission_outcome: Mapped[str] = mapped_column(String(16))
    sender_normalized: Mapped[str | None] = mapped_column(Text)
    metadata_allowed: Mapped[dict] = mapped_column(JSONB, default=dict)
    slot_content_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    transport_trust_level: Mapped[str] = mapped_column(String(32), default="fixture")
    status: Mapped[str] = mapped_column(String(16), default="open")
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    resolution: Mapped[str | None] = mapped_column(String(16))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retain_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
