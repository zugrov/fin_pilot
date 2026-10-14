from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def set_context(session: Session, *, tenant_id: UUID | None, user_id: UUID | None) -> None:
    session.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": "" if tenant_id is None else str(tenant_id)},
    )
    session.execute(
        text("SELECT set_config('app.user_id', :user_id, true)"),
        {"user_id": "" if user_id is None else str(user_id)},
    )
