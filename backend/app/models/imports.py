import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Uuid
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
    dataset: Mapped[str] = mapped_column(String(16), default="cash")
    coverage_through: Mapped[date | None] = mapped_column(Date)
    vat_basis: Mapped[str] = mapped_column(String(16), default="net")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_redacted: Mapped[dict] = mapped_column(JSONB, default=dict)
    encrypted_credentials: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
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


class IngestionDelivery(Base):
    __tablename__ = "ingestion_deliveries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    channel: Mapped[str] = mapped_column(String(16))
    delivery_key: Mapped[str] = mapped_column(String(200))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    transport_status: Mapped[str] = mapped_column(String(32))
    envelope_schema_version: Mapped[str | None] = mapped_column(String(16))
    ingest_mode: Mapped[str | None] = mapped_column(String(16))
    period_from: Mapped[date | None] = mapped_column(Date)
    period_to: Mapped[date | None] = mapped_column(Date)
    period_timezone: Mapped[str | None] = mapped_column(String(64))
    control_totals_claim: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    completeness_claim: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    envelope_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    control_totals_calculated: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_status: Mapped[str] = mapped_column(String(32), default="not_checked")
    validation_block_reasons: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IngestionDeliveryPart(Base):
    __tablename__ = "ingestion_delivery_parts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    delivery_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    part_index: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    part_status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
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
    source_revision: Mapped[int | None] = mapped_column(BigInteger)
    operation: Mapped[str] = mapped_column(String(16), default="upsert")


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
    revenue_entry_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    planned_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    budget_line_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    payload_hash: Mapped[str] = mapped_column(String(64))
    last_source_revision: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DatasetCoverage(Base):
    __tablename__ = "dataset_coverage"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    dataset: Mapped[str] = mapped_column(String(32))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    period_timezone: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(String(16))
    claim: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reconciled_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reconciliation_basis: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EmailIngestion(Base):
    __tablename__ = "email_ingestions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    delivery_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    uidvalidity: Mapped[int] = mapped_column(BigInteger)
    uid: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[str | None] = mapped_column(Text)
    attachment_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
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
