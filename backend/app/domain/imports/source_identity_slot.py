from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import Company
from app.models.imports import SourceIdentity


def load_identity_slot(
    session: Session,
    company: Company,
    namespace: str,
    external_id: str,
) -> SourceIdentity | None:
    if not external_id:
        return None
    return session.scalar(
        select(SourceIdentity).where(
            SourceIdentity.tenant_id == company.tenant_id,
            SourceIdentity.company_id == company.id,
            SourceIdentity.namespace == namespace,
            SourceIdentity.external_id == external_id,
        )
    )


def entity_type_conflict(identity: SourceIdentity | None, expected: str) -> str | None:
    if identity is None:
        return None
    if identity.entity_type != expected:
        return "identity_type_conflict"
    return None


def apply_identity_watermark(
    identity: SourceIdentity,
    *,
    source_revision: int | None,
    payload_hash: str | None,
    advance_only: bool,
) -> None:
    if source_revision is not None and (
        identity.last_source_revision is None or source_revision > identity.last_source_revision
    ):
        identity.last_source_revision = source_revision
    if not advance_only and payload_hash:
        identity.payload_hash = payload_hash
