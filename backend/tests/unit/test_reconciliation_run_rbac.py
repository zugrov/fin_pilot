from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.errors import AppError
from app.models.identity import Membership, User
from app.services.reconciliation_run_service import assert_can_persist_run


def _membership(role: str = "accountant") -> Membership:
    return Membership(
        id=uuid4(),
        tenant_id=uuid4(),
        user_id=uuid4(),
        role=role,
        created_at=datetime.now(UTC),
    )


def test_assert_can_persist_run_requires_verified_email() -> None:
    user = User(
        id=uuid4(),
        email="a@example.com",
        normalized_email="a@example.com",
        name="A",
        password_hash="x",
        created_at=datetime.now(UTC),
        email_verified_at=None,
    )
    access = SimpleNamespace(role_override="accountant")
    with pytest.raises(AppError) as exc:
        assert_can_persist_run(_membership(), access, user)
    assert exc.value.code == "email_unverified"


def test_viewer_cannot_persist_run() -> None:
    user = User(
        id=uuid4(),
        email="v@example.com",
        normalized_email="v@example.com",
        name="V",
        password_hash="x",
        created_at=datetime.now(UTC),
        email_verified_at=datetime.now(UTC),
    )
    access = SimpleNamespace(role_override="viewer")
    with pytest.raises(AppError) as exc:
        assert_can_persist_run(_membership("viewer"), access, user)
    assert exc.value.code == "forbidden"
