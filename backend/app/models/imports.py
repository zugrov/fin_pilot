import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SourceConnection(Base):
    __tablename__ = "source_connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("companies.id"))
    type: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(200))
    namespace: Mapped[str] = mapped_column(String(64))
    authoritative: Mapped[bool] = mapped_column(Boolean, default=True)
    wallet_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    format: Mapped[str] = mapped_column(String(16))
    encoding: Mapped[str] = mapped_column(String(32), default="utf-8")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ImportProfile(Base):
    __tablename__ = "import_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    format: Mapped[str] = mapped_column(String(16))
    encoding: Mapped[str] = mapped_column(String(32))
    sheet_name: Mapped[str | None] = mapped_column(String(200))
    column_mapping: Mapped[dict] = mapped_column(JSONB, default=dict)
    date_format: Mapped[str] = mapped_column(String(32), default="YYYY-MM-DD")
    decimal_separator: Mapped[str] = mapped_column(String(1), default=".")
    sign_policy: Mapped[str] = mapped_column(String(16), default="direction")
    schema_version: Mapped[int] = mapped_column(Integer, default=1)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    file_hash: Mapped[str] = mapped_column(String(64))
    file_storage_key: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32))
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_valid: Mapped[int] = mapped_column(Integer, default=0)
    rows_invalid: Mapped[int] = mapped_column(Integer, default=0)
    rows_committed: Mapped[int] = mapped_column(Integer, default=0)
    quality_flags: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RawImportRow(Base):
    __tablename__ = "raw_import_rows"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    batch_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    row_number: Mapped[int] = mapped_column(Integer)
    raw_payload: Mapped[dict] = mapped_column(JSONB)
    normalized_payload: Mapped[dict | None] = mapped_column(JSONB)
    validation_errors: Mapped[list] = mapped_column(JSONB, default=list)
    duplicate_status: Mapped[str] = mapped_column(String(16))
    proposed_action: Mapped[str] = mapped_column(String(16))
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    external_id: Mapped[str | None] = mapped_column(String(128))


class SourceIdentity(Base):
    __tablename__ = "source_identities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    namespace: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(128))
    canonical_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    payload_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ClassificationRule(Base):
    __tablename__ = "classification_rules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    name: Mapped[str] = mapped_column(String(200))
    priority: Mapped[int] = mapped_column(Integer)
    conditions_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    actions_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
