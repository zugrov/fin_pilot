import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ImportSourceFingerprint(Base):
    __tablename__ = "import_source_fingerprints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"))
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    profile_code: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(BigInteger, default=0)
    parser_version: Mapped[str | None] = mapped_column(Text)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ImportRowLineage(Base):
    __tablename__ = "import_row_lineage"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"))
    raw_import_row_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("raw_import_rows.id")
    )
    source_identity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("source_identities.id")
    )
    entity_kind: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    line_index: Mapped[int] = mapped_column(Integer)
    payload_hash: Mapped[str] = mapped_column(String(64))
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SourceCorrectionFinding(Base):
    __tablename__ = "source_correction_finding"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"))
    kind: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text, default="warning")
    fingerprint_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    lineage_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    import_batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_run"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"))
    run_kind: Mapped[str] = mapped_column(Text)
    period_year: Mapped[int] = mapped_column(Integer)
    period_month: Mapped[int] = mapped_column(Integer)
    input_fingerprints: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    input_hashes: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    group_refs: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    engine_version: Mapped[str] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supersedes_run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
