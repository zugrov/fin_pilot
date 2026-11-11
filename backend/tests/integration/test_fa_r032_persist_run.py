"""Прогон сверки bank↔card51: флаг, RBAC, RLS, повтор, scrub, устойчивость."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from app.domain.imports.fa_r03.bank_card51_matching import BankCardMatchReport
from app.errors import AppError
from app.models.identity import Membership, User
from app.models.provenance import ReconciliationRun
from app.security.context import set_context
from app.services.bank_card_reconciliation_service import (
    SampleFolder,
    reconcile_bank_card51_for_company,
)
from app.services.reconciliation_run_service import (
    ENGINE_VERSION,
    QUALITY_FLAG_BANK_CARD51_DISCREPANCY,
    record_bank_card51_run,
)
from sqlalchemy import create_engine, select, text
from tests.integration.conftest import login, open_workspace, pay, register_and_verify

AT = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)
SECRET_PURPOSE = "pii-purpose-token"
SECRET_PARTY = "pii-counterparty-token"


def _company(client, admin, app, fake, email: str) -> tuple[str, str, str]:
    register_and_verify(client, admin, email)
    login(client, email)
    tenant_id = open_workspace(client, "Сверка")
    company = client.post(
        f"/api/v1/workspaces/{tenant_id}/companies",
        json={"name": "Фирма", "kind": "company"},
    )
    assert company.status_code == 200, company.text
    company_id = company.json()["id"]
    pay(client, app, fake, 1, "month")
    activated = client.post(f"/api/v1/billing/companies/{company_id}/activate")
    assert activated.status_code == 200, activated.text
    with admin.connect() as connection:
        user_id = connection.execute(
            text(
                "SELECT user_id FROM memberships "
                "WHERE tenant_id = :t AND role = 'owner'"
            ),
            {"t": tenant_id},
        ).scalar_one()
    return str(tenant_id), str(company_id), str(user_id)


def _session_for(app, tenant_id: str, user_id: str):
    session = app.state.session_factory()
    set_context(
        session,
        tenant_id=uuid.UUID(tenant_id),
        user_id=uuid.UUID(user_id),
    )
    user = session.get(User, uuid.UUID(user_id))
    membership = session.scalar(
        select(Membership).where(
            Membership.tenant_id == uuid.UUID(tenant_id),
            Membership.user_id == uuid.UUID(user_id),
        )
    )
    assert user is not None
    assert membership is not None
    return session, user, membership


def _settings(app, enabled: bool):
    return app.state.settings.model_copy(
        update={"reconciliation_run_persist_enabled": enabled}
    )


def _samples(folder) -> SampleFolder:
    folder.mkdir(parents=True, exist_ok=True)
    bank = folder / "s1.txt"
    card = folder / "s2.bin"
    bank.write_bytes(b"s1-synthetic")
    card.write_bytes(b"s2-synthetic")
    return SampleFolder(s1=bank, s2=card, s3=None)


def _report(*, aligned: bool, not_found_bank: int) -> dict:
    return {
        "quality": "ok",
        "control_totals": {
            "aligned": aligned,
            "tolerance": "0.00",
            "sources": [],
        },
        "daily_chain": {"sections": 0, "errors_count": 0, "error_codes": []},
        "matching": {
            "matched_pair": 0 if not_found_bank else 1,
            "group_matched_equivalent": 0,
            "needs_confirmation_groups": 0,
            "not_found_bank": not_found_bank,
            "not_found_card": 0,
            "stage1_ambiguous": 0,
        },
    }


def _patch_calculation(monkeypatch, queued: list[dict]) -> None:
    def _calc(_samples, *, year: int, month: int):
        empty = BankCardMatchReport(bank_count=0, card_aggregate_count=0)
        return queued.pop(0), empty

    monkeypatch.setattr(
        "app.services.bank_card_reconciliation_service._bank_card51_calculation",
        _calc,
    )


def _reconcile(session, app, folder, user, membership, tenant_id, company_id, *, enabled, at):
    return reconcile_bank_card51_for_company(
        session,
        _settings(app, enabled),
        samples=folder,
        year=2026,
        month=8,
        user=user,
        membership=membership,
        access=None,
        tenant_id=uuid.UUID(tenant_id),
        company_id=uuid.UUID(company_id),
        at=at,
    )


def _run_count(admin) -> int:
    with admin.connect() as connection:
        value = connection.execute(text("SELECT count(*) FROM reconciliation_run")).scalar_one()
    return int(value)


def test_flag_off_does_not_create_run(client, admin, app, fake, tmp_path, monkeypatch) -> None:
    tenant_id, company_id, user_id = _company(
        client, admin, app, fake, "persist-off@example.com"
    )
    _patch_calculation(monkeypatch, [_report(aligned=True, not_found_bank=0)])
    session, user, membership = _session_for(app, tenant_id, user_id)
    try:
        report = _reconcile(
            session,
            app,
            _samples(tmp_path),
            user,
            membership,
            tenant_id,
            company_id,
            enabled=False,
            at=AT,
        )
        assert report["quality"] == "ok"
        session.commit()
    finally:
        session.close()
    assert _run_count(admin) == 0


def test_flag_on_creates_run_and_repeat_appends(
    client, admin, app, fake, tmp_path, monkeypatch
) -> None:
    tenant_id, company_id, user_id = _company(
        client, admin, app, fake, "persist-on@example.com"
    )
    _patch_calculation(
        monkeypatch,
        [
            _report(aligned=True, not_found_bank=0),
            _report(aligned=False, not_found_bank=1),
        ],
    )
    session, user, membership = _session_for(app, tenant_id, user_id)
    folder = _samples(tmp_path)
    try:
        _reconcile(
            session,
            app,
            folder,
            user,
            membership,
            tenant_id,
            company_id,
            enabled=True,
            at=AT,
        )
        _reconcile(
            session,
            app,
            folder,
            user,
            membership,
            tenant_id,
            company_id,
            enabled=True,
            at=AT + timedelta(seconds=1),
        )
        session.commit()
    finally:
        session.close()

    with admin.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, run_kind, metrics, supersedes_run_id, engine_version, "
                "input_fingerprints::text AS fingerprints, "
                "created_by_user_id "
                "FROM reconciliation_run ORDER BY created_at, id"
            )
        ).mappings().all()
        cash = connection.execute(text("SELECT count(*) FROM cash_transactions")).scalar_one()
        revenue = connection.execute(text("SELECT count(*) FROM revenue_entries")).scalar_one()
        matches = connection.execute(text("SELECT count(*) FROM payment_matches")).scalar_one()
    assert len(rows) == 2
    assert rows[0]["run_kind"] == "bank_card_51"
    assert rows[1]["run_kind"] == "bank_card_51"
    assert rows[0]["engine_version"] == ENGINE_VERSION
    assert rows[0]["metrics"]["status"] == "passed"
    assert "quality_flag" not in rows[0]["metrics"]
    assert rows[0]["supersedes_run_id"] is None
    assert rows[1]["supersedes_run_id"] == rows[0]["id"]
    assert rows[1]["metrics"]["status"] == "completed_with_warnings"
    assert rows[1]["metrics"]["quality_flag"] == QUALITY_FLAG_BANK_CARD51_DISCREPANCY
    assert rows[0]["created_by_user_id"] == uuid.UUID(user_id)
    assert "s1.txt" not in rows[0]["fingerprints"]
    assert "payment_id" not in str(rows[0]["metrics"])
    assert "payment_id" not in str(rows[1]["metrics"])
    assert int(cash) == 0
    assert int(revenue) == 0
    assert int(matches) == 0


def test_rbac_requires_finance_write_and_verified_email(
    client, admin, app, fake, tmp_path, monkeypatch
) -> None:
    tenant_id, company_id, user_id = _company(
        client, admin, app, fake, "persist-rbac@example.com"
    )
    _patch_calculation(
        monkeypatch,
        [
            _report(aligned=True, not_found_bank=0),
            _report(aligned=True, not_found_bank=0),
            _report(aligned=True, not_found_bank=0),
        ],
    )
    session, user, membership = _session_for(app, tenant_id, user_id)
    folder = _samples(tmp_path)
    try:
        membership.role = "viewer"
        session.flush()
        with pytest.raises(AppError) as viewer_error:
            _reconcile(
                session,
                app,
                folder,
                user,
                membership,
                tenant_id,
                company_id,
                enabled=True,
                at=AT,
            )
        assert viewer_error.value.code == "forbidden"

        membership.role = "operator"
        session.flush()
        with pytest.raises(AppError) as operator_error:
            _reconcile(
                session,
                app,
                folder,
                user,
                membership,
                tenant_id,
                company_id,
                enabled=True,
                at=AT,
            )
        assert operator_error.value.code == "forbidden"

        membership.role = "owner"
        user.email_verified_at = None
        session.flush()
        with pytest.raises(AppError) as email_error:
            _reconcile(
                session,
                app,
                folder,
                user,
                membership,
                tenant_id,
                company_id,
                enabled=True,
                at=AT,
            )
        assert email_error.value.code == "email_unverified"
        session.commit()
    finally:
        session.close()
    assert _run_count(admin) == 0


def test_other_tenant_cannot_see_run(client, admin, app, fake, tmp_path, monkeypatch) -> None:
    tenant_a, company_a, user_a = _company(
        client, admin, app, fake, "persist-rls-a@example.com"
    )
    tenant_b, company_b, user_b = _company(
        client, admin, app, fake, "persist-rls-b@example.com"
    )
    _patch_calculation(
        monkeypatch,
        [
            _report(aligned=True, not_found_bank=0),
            _report(aligned=True, not_found_bank=0),
        ],
    )
    session_a, user_a_row, membership_a = _session_for(app, tenant_a, user_a)
    try:
        _reconcile(
            session_a,
            app,
            _samples(tmp_path),
            user_a_row,
            membership_a,
            tenant_a,
            company_a,
            enabled=True,
            at=AT,
        )
        session_a.commit()
    finally:
        session_a.close()

    session_b, user_b_row, membership_b = _session_for(app, tenant_b, user_b)
    try:
        _reconcile(
            session_b,
            app,
            _samples(tmp_path / "b"),
            user_b_row,
            membership_b,
            tenant_b,
            company_b,
            enabled=True,
            at=AT + timedelta(seconds=1),
        )
        own = session_b.scalars(select(ReconciliationRun)).all()
        assert len(own) == 1
        assert own[0].supersedes_run_id is None
        assert own[0].company_id == uuid.UUID(company_b)
        session_b.commit()
    finally:
        session_b.close()

    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with engine.connect() as connection:
            connection.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": tenant_b},
            )
            visible = connection.execute(
                text("SELECT count(*) FROM reconciliation_run")
            ).scalar_one()
            foreign = connection.execute(
                text("SELECT count(*) FROM reconciliation_run WHERE company_id = :c"),
                {"c": company_a},
            ).scalar_one()
        assert int(visible) == 1
        assert int(foreign) == 0
    finally:
        engine.dispose()


def test_stored_metrics_scrub_pii(client, admin, app, fake) -> None:
    tenant_id, company_id, user_id = _company(
        client, admin, app, fake, "persist-scrub@example.com"
    )
    session, user, membership = _session_for(app, tenant_id, user_id)
    try:
        row = record_bank_card51_run(
            session,
            _settings(app, True),
            tenant_id=uuid.UUID(tenant_id),
            company_id=uuid.UUID(company_id),
            user=user,
            membership=membership,
            access=None,
            period_year=2026,
            period_month=8,
            aligned=True,
            chain_error_count=0,
            matching={
                "matched_pair": 1,
                "group_matched_equivalent": 0,
                "needs_confirmation_groups": 0,
                "not_found_bank": 0,
                "not_found_card": 0,
                "stage1_ambiguous": 0,
            },
            group_refs=[
                {
                    "business_date": "2026-08-03",
                    "direction": "in",
                    "amount": "10.00",
                    "kind": "matched_pair",
                    "bank_documents": 1,
                    "card_aggregates": 1,
                    "payee": SECRET_PARTY,
                    "description": SECRET_PURPOSE,
                }
            ],
            control_totals={
                "aligned": True,
                "tolerance": "0.00",
                "sources": [],
                "purpose": SECRET_PURPOSE,
                "counterparty_name": SECRET_PARTY,
            },
            input_fingerprints=[
                {
                    "role": "s1",
                    "profile_code": "ru-bank-clientbank/1.0.0",
                    "content_sha256": "abc",
                    "byte_size": 3,
                    "purpose": SECRET_PURPOSE,
                    "payer": SECRET_PARTY,
                }
            ],
            input_hashes={
                "canonical_sha256": "def",
                "counterparty": SECRET_PARTY,
            },
            at=AT,
        )
        assert row is not None
        session.commit()
    finally:
        session.close()

    with admin.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT metrics::text || group_refs::text || "
                "input_fingerprints::text || input_hashes::text "
                "FROM reconciliation_run"
            )
        ).scalar_one()
    assert SECRET_PURPOSE not in stored
    assert SECRET_PARTY not in stored
    assert "matched_pair" in stored
    assert '"status": "passed"' in stored or '"status":"passed"' in stored


def test_persist_failure_keeps_report_and_logs_without_pii(
    client, admin, app, fake, tmp_path, monkeypatch
) -> None:
    tenant_id, company_id, user_id = _company(
        client, admin, app, fake, "persist-fail@example.com"
    )
    report = _report(aligned=True, not_found_bank=0)
    report["control_totals"]["purpose"] = SECRET_PURPOSE
    _patch_calculation(monkeypatch, [report])

    def _boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "app.services.reconciliation_run_service.persist_reconciliation_run",
        _boom,
    )
    session, user, membership = _session_for(app, tenant_id, user_id)
    try:
        with patch("app.services.reconciliation_run_service.logger.error") as logged:
            returned = _reconcile(
                session,
                app,
                _samples(tmp_path),
                user,
                membership,
                tenant_id,
                company_id,
                enabled=True,
                at=AT,
            )
        assert returned["control_totals"]["purpose"] == SECRET_PURPOSE
        logged.assert_called_once()
        parts = [str(part) for part in logged.call_args[0]]
        message = " ".join(parts)
        assert message.startswith("reconciliation_run_persist_failed")
        assert SECRET_PURPOSE not in message
        assert "persist-fail@example.com" not in message
        assert company_id in message
        session.commit()
    finally:
        session.close()
    assert _run_count(admin) == 0
    with admin.connect() as connection:
        audits = connection.execute(
            text(
                "SELECT count(*) FROM audit_log "
                "WHERE action = 'reconciliation_run_recorded'"
            )
        ).scalar_one()
    assert int(audits) == 0


def test_readonly_get_does_not_persist_when_flag_on(
    client, admin, app, fake, monkeypatch
) -> None:
    _tenant_id, company_id, _user_id = _company(
        client, admin, app, fake, "persist-get@example.com"
    )
    monkeypatch.setattr(
        "app.api.v1.reconciliation.report_for_company_local",
        lambda **_kwargs: {"quality": "ok"},
    )
    app.state.settings = app.state.settings.model_copy(
        update={
            "fa_r03_local_reconciliation_enabled": True,
            "fa_r03_local_samples_root": "/tmp",
            "fa_r03_local_reconciliation_company_id": company_id,
            "reconciliation_run_persist_enabled": True,
        }
    )
    response = client.get(
        f"/api/v1/companies/{company_id}/reconciliation/bank-card-51",
        params={"year": 2026, "month": 8},
    )
    assert response.status_code == 200, response.text
    assert _run_count(admin) == 0
