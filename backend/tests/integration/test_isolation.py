from app.clock import now
from app.jobs.finance import assert_financial_job
from sqlalchemy import text
from tests.integration.conftest import login, open_workspace, register_and_verify


def _owner(client, admin, email: str, company_name: str) -> tuple[str, str]:
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, email)
    created = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": company_name, "inn": "7700000000", "kind": "company"},
    )
    assert created.status_code == 200, created.text
    return tenant_id, created.json()["id"]


def test_s1_and_s2_other_tenant_is_invisible(client, admin, app) -> None:
    from fastapi.testclient import TestClient

    _tenant_a, company_a = _owner(client, admin, "a@example.com", "Альфа")
    other = TestClient(app)
    _tenant_b, company_b = _owner(other, admin, "b@example.com", "Бета")
    foreign = client.get(f"/api/v1/companies/{company_b}")
    assert foreign.status_code == 404
    export = client.get(f"/api/v1/companies/{company_b}/export")
    assert export.status_code == 404
    summary = client.get(f"/api/v1/workspaces/{_tenant_a}/group-summary?company_ids={company_b}")
    assert summary.status_code == 200
    assert company_b not in summary.json()["scope_company_ids"]
    assert summary.json()["metrics"]["cash_total"] is None
    with admin.connect() as connection:
        user_a = connection.execute(
            text("SELECT id FROM users WHERE normalized_email = 'a@example.com'")
        ).scalar_one()
        tenant_b = connection.execute(
            text("SELECT tenant_id FROM companies WHERE id = :id"),
            {"id": company_b},
        ).scalar_one()
    session = app.state.session_factory()
    try:
        try:
            assert_financial_job(
                session,
                user_id=user_a,
                tenant_id=tenant_b,
                company_id=company_b,
                at=now(),
                grace_days=3,
                bypass=False,
            )
            raised = False
        except Exception as exc:
            raised = True
            assert getattr(exc, "status_code", None) in {403, 404}
        assert raised is True
    finally:
        session.close()
    own = client.get(f"/api/v1/companies/{company_a}")
    assert own.status_code == 200


def test_s3_tenant_context_does_not_leak_across_transactions(client, admin, app) -> None:
    tenant_id, _company = _owner(client, admin, "pool@example.com", "Пул")
    engine = app.state.engine
    with engine.connect() as connection:
        first = connection.begin()
        set_context_raw(connection, tenant_id)
        visible = connection.execute(text("SELECT count(*) FROM companies")).scalar_one()
        assert visible == 1
        first.commit()
        second = connection.begin()
        current = connection.execute(
            text("SELECT current_setting('app.tenant_id', true)")
        ).scalar_one()
        hidden = connection.execute(text("SELECT count(*) FROM companies")).scalar_one()
        second.rollback()
    assert current in {"", None}
    assert hidden == 0
    with admin.connect() as connection:
        role = connection.execute(
            text(
                "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = 'finpilot_app'"
            )
        ).one()
    assert role.rolsuper is False
    assert role.rolbypassrls is False


def test_company_list_returns_stored_timezone(client, admin) -> None:
    tenant_id, company_id = _owner(client, admin, "zone@example.com", "Зона")
    listed = client.get(f"/api/v1/workspaces/{tenant_id}/companies")
    assert listed.status_code == 200, listed.text
    row = next(item for item in listed.json()["companies"] if item["id"] == company_id)
    assert row["timezone"] == "Europe/Moscow"
    with admin.connect() as connection:
        connection.execute(
            text("UPDATE companies SET timezone = 'America/Los_Angeles' WHERE id = :id"),
            {"id": company_id},
        )
        connection.commit()
    again = client.get(f"/api/v1/workspaces/{tenant_id}/companies")
    stored = next(item for item in again.json()["companies"] if item["id"] == company_id)
    assert stored["timezone"] == "America/Los_Angeles"


def set_context_raw(connection, tenant_id: str) -> None:
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )
    connection.execute(text("SELECT set_config('app.user_id', '', true)"))
