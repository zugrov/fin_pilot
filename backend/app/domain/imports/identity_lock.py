import hashlib
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session


def identity_advisory_lock_key(
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    namespace: str,
    external_id: str,
) -> int:
    blob = f"{tenant_id}:{company_id}:{namespace}:{external_id}".encode()
    digest = hashlib.sha256(blob).digest()
    value = int.from_bytes(digest[:8], "big", signed=False)
    return value % (2**63 - 1)


def lock_identity_keys(
    session: Session,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    keys: list[tuple[str, str]],
) -> None:
    for namespace, external_id in sorted(keys):
        key = identity_advisory_lock_key(tenant_id, company_id, namespace, external_id)
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
