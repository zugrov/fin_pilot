"""Один замер нагрузки. Обычный pytest и CI этот скрипт не вызывают."""

import os
import platform
import sys
import time
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_PORT = os.environ.setdefault("TEST_PG_PORT", "5433")
os.environ["DATABASE_URL"] = (
    f"postgresql+psycopg://finpilot_app:finpilot_test_only@127.0.0.1:{_PORT}/finpilot_test"
)
os.environ["WORKER_DATABASE_URL"] = (
    f"postgresql+psycopg://finpilot_worker:finpilot_test_only@127.0.0.1:{_PORT}/finpilot_test"
)
os.environ["MIGRATION_DATABASE_URL"] = (
    f"postgresql+psycopg://127.0.0.1:{_PORT}/finpilot_test"
)

from app.config import Settings  # noqa: E402
from app.integrations.payments import FakeYooKassa  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models.identity import Company, Membership, User  # noqa: E402
from app.security.context import set_context  # noqa: E402
from app.services.cash_service import create_transaction  # noqa: E402
from app.services.forecast_service import company_forecast  # noqa: E402
from app.services.import_service import commit_import, receive_import  # noqa: E402
from app.services.report_service import dashboard_payload  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from tests.integration.conftest import (  # noqa: E402
    login,
    open_workspace,
    pay,
    register_and_verify,
)

FIXTURES = ROOT / "tests" / "fixtures" / "imports"

ROWS = 10_000
PERIOD = (date(2026, 10, 1), date(2026, 10, 31))


def _ready(client: TestClient, admin, app, fake) -> tuple[str, str, str]:
    register_and_verify(client, admin, "load-measure@example.com")
    login(client, "load-measure@example.com")
    tenant_id = open_workspace(client, "Нагрузка")
    company = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Нагрузка", "kind": "company"},
    )
    assert company.status_code == 200, company.text
    company_id = company.json()["id"]
    pay(client, app, fake, 1, "month")
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    wallet = client.post(
        f"/api/v1/companies/{company_id}/wallets",
        json={"name": "Расчётный", "type": "bank", "code": "main"},
        headers={"Idempotency-Key": "measure-load-wallet"},
    )
    assert wallet.status_code == 200, wallet.text
    opened = client.post(
        f"/api/v1/wallets/{wallet.json()['id']}/opening-balance",
        json={"effective_at": "2026-10-01T00:00:00+00:00", "amount": "0.00"},
        headers={"Idempotency-Key": "measure-load-opening"},
    )
    assert opened.status_code == 200, opened.text
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200, me.text
    return tenant_id, company_id, wallet.json()["id"]


def _insert(app, tenant_id: str, company_id: str, user_id: str, wallet_id: str) -> float:
    started = time.perf_counter()
    session = app.state.session_factory()
    try:
        set_context(session, tenant_id=UUID(tenant_id), user_id=UUID(user_id))
        company = session.get(Company, UUID(company_id))
        user = session.get(User, UUID(user_id))
        membership = session.scalar(
            select(Membership).where(
                Membership.tenant_id == UUID(tenant_id),
                Membership.user_id == UUID(user_id),
            )
        )
        assert company is not None and user is not None and membership is not None
        moment = datetime(2026, 10, 14, 12, tzinfo=UTC)
        wallet = UUID(wallet_id)
        for index in range(ROWS):
            create_transaction(
                session,
                membership,
                company,
                user,
                wallet_id=wallet,
                business_date=date(2026, 10, 10),
                occurred_at=moment,
                direction="out",
                amount=Decimal("1.00"),
                category_id=None,
                description="",
                status="posted",
                idempotency_key=f"load-{index}",
                request_hash=f"load-{index}",
                at=moment,
            )
            if index % 500 == 499:
                session.commit()
                # set_config локален для транзакции и сбрасывается на commit.
                set_context(session, tenant_id=UUID(tenant_id), user_id=UUID(user_id))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return time.perf_counter() - started


def _timed(label: str, action) -> str:
    started = time.perf_counter()
    action()
    seconds = time.perf_counter() - started
    return f"{label}: {seconds:.3f} с"


def main() -> None:
    database_url = os.environ["DATABASE_URL"]
    if ":5432/" in database_url or database_url.rsplit("/", 1)[-1] != "finpilot_test":
        raise SystemExit("замер только для базы finpilot_test на порту 5433")
    admin = create_engine(os.environ["MIGRATION_DATABASE_URL"])
    app = create_app(Settings())
    app.state.import_storage_dir = str(ROOT / "var" / "load-imports")
    app.state.settings.import_storage_dir = app.state.import_storage_dir
    fake = FakeYooKassa(shop_id="shop-test")
    app.state.payment_provider_factory = lambda: fake
    with TestClient(app) as client:
        tenant_id, company_id, wallet_id = _ready(client, admin, app, fake)
        me = client.get("/api/v1/auth/me").json()
        user_id = me["user"]["id"]
        insert_seconds = _insert(app, tenant_id, company_id, user_id, wallet_id)
        session = app.state.session_factory()
        try:
            set_context(session, tenant_id=UUID(tenant_id), user_id=UUID(user_id))
            company = session.get(Company, UUID(company_id))
            moment = datetime(2026, 10, 14, 12, tzinfo=UTC)

            def forecast() -> None:
                company_forecast(session, company, date(2026, 10, 14), "base", moment)

            def board() -> None:
                dashboard_payload(session, company, moment, PERIOD)

            forecast_line = _timed("прогноз 91 день", forecast)
            board_line = _timed("дашборд", board)
        finally:
            session.close()
        source = client.post(
            f"/api/v1/companies/{company_id}/sources",
            json={
                "name": "Деньги",
                "type": "file",
                "namespace": f"load-{uuid4().hex[:8]}",
                "format": "csv",
                "dataset": "cash",
                "wallet_id": wallet_id,
            },
        )
        assert source.status_code == 200, source.text
        started = time.perf_counter()
        session = app.state.session_factory()
        try:
            set_context(session, tenant_id=UUID(tenant_id), user_id=UUID(user_id))
            company = session.get(Company, UUID(company_id))
            user = session.get(User, UUID(user_id))
            membership = session.scalar(
                select(Membership).where(
                    Membership.tenant_id == UUID(tenant_id),
                    Membership.user_id == UUID(user_id),
                )
            )
            assert company is not None and user is not None and membership is not None
            moment = datetime(2026, 10, 14, 12, tzinfo=UTC)
            preview = receive_import(
                session,
                membership,
                company,
                user,
                app.state.settings,
                connection_id=UUID(source.json()["id"]),
                content=(FIXTURES / "cash_ok.csv").read_bytes(),
                idempotency_key=uuid4().hex,
                at=moment,
            )
            commit_import(
                session,
                membership,
                user,
                app.state.settings,
                UUID(preview["id"]),
                moment,
            )
            session.commit()
        finally:
            session.close()
        import_seconds = time.perf_counter() - started
    print(f"машина: {platform.platform()}, CPU: {os.cpu_count()}")
    print(f"проведённых операций: {ROWS}")
    print(f"запись операций: {insert_seconds:.3f} с")
    print(forecast_line)
    print(board_line)
    print(f"импорт cash_ok.csv: {import_seconds:.3f} с")
    print("профиль ТЗ 4 vCPU и 100 000 операций этим прогоном не проверялся")


if __name__ == "__main__":
    main()
