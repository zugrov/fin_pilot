"""FA-R03.3-min: fingerprint и lineage после commit импорта."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.models.imports import ImportBatch, RawImportRow, SourceConnection
from app.models.provenance import ImportRowLineage, ImportSourceFingerprint
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class LineageEvent:
    row: RawImportRow
    entity_kind: str
    entity_id: uuid.UUID
    source_identity_id: uuid.UUID | None


def profile_code_for(connection: SourceConnection) -> str:
    return f"{connection.namespace}/{connection.format}"


def register_batch_fingerprint(
    session: Session,
    company_id: uuid.UUID,
    tenant_id: uuid.UUID,
    batch: ImportBatch,
    connection: SourceConnection,
    at: datetime,
    *,
    byte_size: int = 0,
    period_from=None,
    period_to=None,
) -> ImportSourceFingerprint:
    profile = profile_code_for(connection)
    stmt = (
        insert(ImportSourceFingerprint)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            company_id=company_id,
            import_batch_id=batch.id,
            profile_code=profile,
            content_sha256=batch.file_hash,
            byte_size=byte_size,
            parser_version=str(connection.format),
            period_from=period_from,
            period_to=period_to,
            registered_at=at,
        )
        .on_conflict_do_update(
            index_elements=["tenant_id", "company_id", "profile_code", "content_sha256"],
            set_={"import_batch_id": batch.id, "registered_at": at},
        )
        .returning(ImportSourceFingerprint)
    )
    row = session.scalars(stmt).one()
    session.flush()
    return row


def record_lineage_events(
    session: Session,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    events: list[LineageEvent],
    at: datetime,
) -> None:
    for event in events:
        session.add(
            ImportRowLineage(
                tenant_id=tenant_id,
                company_id=company_id,
                raw_import_row_id=event.row.id,
                source_identity_id=event.source_identity_id,
                entity_kind=event.entity_kind,
                entity_id=event.entity_id,
                line_index=event.row.row_number,
                payload_hash=event.row.payload_hash or "",
                linked_at=at,
            )
        )
    if events:
        session.flush()


def fingerprint_for_batch(session: Session, tenant_id: uuid.UUID, batch_id: uuid.UUID):
    return session.scalar(
        select(ImportSourceFingerprint).where(
            ImportSourceFingerprint.tenant_id == tenant_id,
            ImportSourceFingerprint.import_batch_id == batch_id,
        )
    )
