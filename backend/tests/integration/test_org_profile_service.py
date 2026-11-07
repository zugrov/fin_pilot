import uuid
from datetime import UTC, date, datetime

import pytest
from app.domain.org_profile.validation import ProfileSnapshot
from app.errors import AppError
from app.models.identity import CompanyAccess, Membership
from app.models.org_profile import OrganizationProfileVersion
from app.services.org_profile_service import (
    assert_first_day_of_month,
    confirm_organization_profile_version,
    create_organization_profile_version,
    get_profile_for_period,
    list_versions_for_company,
    update_draft_profile_version,
)
from app.services.tenant_service import create_company
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from tests.integration.balances_test_util import assert_finpilot_test_database


@pytest.fixture(autouse=True)
def _guard_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


def _complete_snapshot(**kwargs) -> ProfileSnapshot:
    base = dict(
        org_form="ooo",
        tax_system="usn",
        usn_tax_object="income",
        vat_status="not_applicable",
        accounting_source="onec",
        money_channels=["bank"],
        month_close_policy="calendar_month_end",
        revenue_recognition_method="accrual",
        is_new_organization=True,
    )
    base.update(kwargs)
    return ProfileSnapshot(**base)


def _seed_company(engine, *, tenant_name: str = "t") -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    tenant_id = uuid.uuid4()
    company_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO tenants (id, name, created_at) VALUES (:id, :n, now())"),
            {"id": tenant_id, "n": tenant_name},
        )
        email = f"o-{uuid.uuid4().hex}@example.com"
        connection.execute(
            text(
                "INSERT INTO users (id, email, normalized_email, password_hash, name, created_at) "
                "VALUES (:id, :e, :e, 'x', 'u', now())"
            ),
            {"id": owner_id, "e": email},
        )
        connection.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at) "
                "VALUES (:id, :t, :u, 'owner', now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "u": owner_id},
        )
        connection.execute(
            text(
                "INSERT INTO companies "
                "(id, tenant_id, name, kind, timezone, inn, created_at, updated_at) "
                "VALUES (:id, :t, 'c', 'company', 'Europe/Moscow', '7707083893', now(), now())"
            ),
            {"id": company_id, "t": tenant_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO organization_profile_versions (
                  id, tenant_id, company_id, effective_from, change_reason
                ) VALUES (gen_random_uuid(), :t, :c, '2026-01-01', 'bootstrap')
                """
            ),
            {"t": tenant_id, "c": company_id},
        )
    return tenant_id, company_id, owner_id


def _membership(session: Session, tenant_id: uuid.UUID, user_id: uuid.UUID) -> Membership:
    return session.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant_id,
            Membership.user_id == user_id,
        )
    )


def test_create_version_rejects_non_first_of_month(migrated_database) -> None:
    tenant_id, company_id, owner_id = _seed_company(migrated_database)
    with Session(migrated_database) as session:
        with pytest.raises(AppError) as exc:
            create_organization_profile_version(
                session,
                tenant_id=tenant_id,
                company_id=company_id,
                created_by=owner_id,
                effective_from=date(2026, 2, 15),
                snapshot=_complete_snapshot(),
                change_reason="bad date",
                at=datetime.now(UTC),
            )
        assert exc.value.code == "invalid_effective_from"


def test_usn_requires_tax_object_on_draft_update(migrated_database) -> None:
    tenant_id, company_id, owner_id = _seed_company(migrated_database)
    snap = ProfileSnapshot(tax_system="usn", usn_tax_object="unspecified")
    with Session(migrated_database) as session:
        version = session.scalar(
            select(OrganizationProfileVersion).where(
                OrganizationProfileVersion.company_id == company_id
            )
        )
        with pytest.raises(AppError) as exc:
            update_draft_profile_version(
                session,
                tenant_id=tenant_id,
                company_id=company_id,
                version_id=version.id,
                snapshot=snap,
                change_reason="bad",
            )
        assert exc.value.code == "profile_validation_failed"
        assert "usn_tax_object" in exc.value.details["field_errors"]


def test_update_draft_and_confirm(migrated_database) -> None:
    tenant_id, company_id, owner_id = _seed_company(migrated_database)
    at = datetime(2026, 5, 1, tzinfo=UTC)
    with Session(migrated_database) as session:
        version = session.scalar(
            select(OrganizationProfileVersion).where(
                OrganizationProfileVersion.company_id == company_id
            )
        )
        update_draft_profile_version(
            session,
            tenant_id=tenant_id,
            company_id=company_id,
            version_id=version.id,
            snapshot=_complete_snapshot(),
            change_reason="filled",
        )
        session.commit()
        version_id = version.id

    with Session(migrated_database) as session:
        membership = _membership(session, tenant_id, owner_id)
        confirmed, audit = confirm_organization_profile_version(
            session,
            tenant_id=tenant_id,
            company_id=company_id,
            version_id=version_id,
            membership=membership,
            access=None,
            at=at,
        )
        session.commit()
        assert confirmed.confirmed_role == "owner"
        assert audit["action"] == "organization_profile_confirmed"

    with Session(migrated_database) as session:
        with pytest.raises(AppError) as exc:
            update_draft_profile_version(
                session,
                tenant_id=tenant_id,
                company_id=company_id,
                version_id=version_id,
                snapshot=_complete_snapshot(org_form="ip"),
                change_reason="late",
            )
        assert exc.value.code == "already_confirmed"


def test_confirm_rejects_viewer(migrated_database) -> None:
    tenant_id, company_id, owner_id = _seed_company(migrated_database)
    viewer_id = uuid.uuid4()
    with migrated_database.begin() as connection:
        email = f"v-{uuid.uuid4().hex}@example.com"
        connection.execute(
            text(
                "INSERT INTO users (id, email, normalized_email, password_hash, name, created_at) "
                "VALUES (:id, :e, :e, 'x', 'u', now())"
            ),
            {"id": viewer_id, "e": email},
        )
        connection.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at) "
                "VALUES (:id, :t, :u, 'viewer', now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "u": viewer_id},
        )
        connection.execute(
            text(
                "INSERT INTO company_access (tenant_id, user_id, company_id) "
                "VALUES (:t, :u, :c)"
            ),
            {"t": tenant_id, "u": viewer_id, "c": company_id},
        )

    with Session(migrated_database) as session:
        version = session.scalar(
            select(OrganizationProfileVersion).where(
                OrganizationProfileVersion.company_id == company_id
            )
        )
        membership = _membership(session, tenant_id, viewer_id)
        access = session.scalar(
            select(CompanyAccess).where(
                CompanyAccess.user_id == viewer_id,
                CompanyAccess.company_id == company_id,
            )
        )
        with pytest.raises(AppError) as exc:
            confirm_organization_profile_version(
                session,
                tenant_id=tenant_id,
                company_id=company_id,
                version_id=version.id,
                membership=membership,
                access=access,
                at=datetime.now(UTC),
            )
        assert exc.value.code == "forbidden"


def test_confirm_accountant_allowed(migrated_database) -> None:
    tenant_id, company_id, _ = _seed_company(migrated_database)
    accountant_id = uuid.uuid4()
    with migrated_database.begin() as connection:
        email = f"a-{uuid.uuid4().hex}@example.com"
        connection.execute(
            text(
                "INSERT INTO users (id, email, normalized_email, password_hash, name, created_at) "
                "VALUES (:id, :e, :e, 'x', 'u', now())"
            ),
            {"id": accountant_id, "e": email},
        )
        connection.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at) "
                "VALUES (:id, :t, :u, 'accountant', now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "u": accountant_id},
        )
        connection.execute(
            text(
                "INSERT INTO company_access (tenant_id, user_id, company_id) "
                "VALUES (:t, :u, :c)"
            ),
            {"t": tenant_id, "u": accountant_id, "c": company_id},
        )

    with Session(migrated_database) as session:
        version = session.scalar(
            select(OrganizationProfileVersion).where(
                OrganizationProfileVersion.company_id == company_id
            )
        )
        update_draft_profile_version(
            session,
            tenant_id=tenant_id,
            company_id=company_id,
            version_id=version.id,
            snapshot=_complete_snapshot(),
            change_reason="ok",
        )
        membership = _membership(session, tenant_id, accountant_id)
        access = session.scalar(
            select(CompanyAccess).where(
                CompanyAccess.user_id == accountant_id,
                CompanyAccess.company_id == company_id,
            )
        )
        row, _ = confirm_organization_profile_version(
            session,
            tenant_id=tenant_id,
            company_id=company_id,
            version_id=version.id,
            membership=membership,
            access=access,
            at=datetime.now(UTC),
        )
        session.commit()
        assert row.confirmed_role == "accountant"


def test_confirm_incomplete_profile_400(migrated_database) -> None:
    tenant_id, company_id, owner_id = _seed_company(migrated_database)
    with Session(migrated_database) as session:
        version = session.scalar(
            select(OrganizationProfileVersion).where(
                OrganizationProfileVersion.company_id == company_id
            )
        )
        membership = _membership(session, tenant_id, owner_id)
        with pytest.raises(AppError) as exc:
            confirm_organization_profile_version(
                session,
                tenant_id=tenant_id,
                company_id=company_id,
                version_id=version.id,
                membership=membership,
                access=None,
                at=datetime.now(UTC),
            )
        assert exc.value.code == "profile_confirm_incomplete"
        assert "_confirm_minimum" in exc.value.details.get("field_errors", {})


def test_confirm_twice_409(migrated_database) -> None:
    tenant_id, company_id, owner_id = _seed_company(migrated_database)
    with Session(migrated_database) as session:
        version = session.scalar(
            select(OrganizationProfileVersion).where(
                OrganizationProfileVersion.company_id == company_id
            )
        )
        update_draft_profile_version(
            session,
            tenant_id=tenant_id,
            company_id=company_id,
            version_id=version.id,
            snapshot=_complete_snapshot(),
            change_reason="ok",
        )
        membership = _membership(session, tenant_id, owner_id)
        confirm_organization_profile_version(
            session,
            tenant_id=tenant_id,
            company_id=company_id,
            version_id=version.id,
            membership=membership,
            access=None,
            at=datetime.now(UTC),
        )
        with pytest.raises(AppError) as exc:
            confirm_organization_profile_version(
                session,
                tenant_id=tenant_id,
                company_id=company_id,
                version_id=version.id,
                membership=membership,
                access=None,
                at=datetime.now(UTC),
            )
        assert exc.value.code == "already_confirmed"


def test_confirm_wrong_tenant_404(migrated_database) -> None:
    t1, c1, owner1 = _seed_company(migrated_database)
    t2, _, _ = _seed_company(migrated_database, tenant_name="other")
    with Session(migrated_database) as session:
        version = session.scalar(
            select(OrganizationProfileVersion).where(
                OrganizationProfileVersion.company_id == c1
            )
        )
        membership = _membership(session, tenant_id=t1, user_id=owner1)
        with pytest.raises(AppError) as exc:
            confirm_organization_profile_version(
                session,
                tenant_id=t2,
                company_id=c1,
                version_id=version.id,
                membership=membership,
                access=None,
                at=datetime.now(UTC),
            )
        assert exc.value.code == "not_found"


def test_confirm_not_latest_rejected(migrated_database) -> None:
    tenant_id, company_id, owner_id = _seed_company(migrated_database)
    with Session(migrated_database) as session:
        bootstrap = session.scalar(
            select(OrganizationProfileVersion).where(
                OrganizationProfileVersion.company_id == company_id
            )
        )
        update_draft_profile_version(
            session,
            tenant_id=tenant_id,
            company_id=company_id,
            version_id=bootstrap.id,
            snapshot=_complete_snapshot(),
            change_reason="fill",
        )
        confirm_organization_profile_version(
            session,
            tenant_id=tenant_id,
            company_id=company_id,
            version_id=bootstrap.id,
            membership=_membership(session, tenant_id, owner_id),
            access=None,
            at=datetime.now(UTC),
        )
        newer = create_organization_profile_version(
            session,
            tenant_id=tenant_id,
            company_id=company_id,
            created_by=owner_id,
            effective_from=date(2026, 4, 1),
            snapshot=_complete_snapshot(),
            change_reason="newer",
            at=datetime.now(UTC),
        )
        session.commit()
        with pytest.raises(AppError) as exc:
            confirm_organization_profile_version(
                session,
                tenant_id=tenant_id,
                company_id=company_id,
                version_id=bootstrap.id,
                membership=_membership(session, tenant_id, owner_id),
                access=None,
                at=datetime.now(UTC),
            )
        assert exc.value.code == "not_latest_version"
        assert newer.confirmed_at is None


def test_create_blocked_while_draft_exists(migrated_database) -> None:
    tenant_id, company_id, owner_id = _seed_company(migrated_database)
    with Session(migrated_database) as session:
        with pytest.raises(AppError) as exc:
            create_organization_profile_version(
                session,
                tenant_id=tenant_id,
                company_id=company_id,
                created_by=owner_id,
                effective_from=date(2026, 6, 1),
                snapshot=_complete_snapshot(),
                change_reason="skip draft",
                at=datetime.now(UTC),
            )
        assert exc.value.code == "draft_exists"


def test_create_company_bootstraps_profile(migrated_database) -> None:
    tenant_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    with migrated_database.begin() as connection:
        connection.execute(
            text("INSERT INTO tenants (id, name, created_at) VALUES (:id, 't', now())"),
            {"id": tenant_id},
        )
        email = f"o-{uuid.uuid4().hex}@example.com"
        connection.execute(
            text(
                "INSERT INTO users (id, email, normalized_email, password_hash, name, created_at) "
                "VALUES (:id, :e, :e, 'x', 'u', now())"
            ),
            {"id": owner_id, "e": email},
        )
    with Session(migrated_database) as session:
        membership = Membership(
            tenant_id=tenant_id,
            user_id=owner_id,
            role="owner",
            status="active",
            created_at=datetime.now(UTC),
        )
        session.add(membership)
        session.flush()
        company = create_company(
            session, membership, name="NewCo", legal_name=None, inn=None, kind="company"
        )
        session.commit()
        company_id = company.id

    with Session(migrated_database) as session:
        versions = list_versions_for_company(session, tenant_id=tenant_id, company_id=company_id)
        assert len(versions) == 1
        assert versions[0].confirmed_at is None


def test_profile_resolution_and_isolation(migrated_database) -> None:
    t1, c1, owner1 = _seed_company(migrated_database, tenant_name="t1")
    t2, c2, _ = _seed_company(migrated_database, tenant_name="t2")
    version_id = None
    with Session(migrated_database) as session:
        version = session.scalar(
            select(OrganizationProfileVersion).where(
                OrganizationProfileVersion.company_id == c1
            )
        )
        version_id = version.id
        update_draft_profile_version(
            session,
            tenant_id=t1,
            company_id=c1,
            version_id=version_id,
            snapshot=_complete_snapshot(),
            change_reason="v1",
        )
        session.commit()

    with Session(migrated_database) as session:
        membership = _membership(session, t1, owner1)
        confirm_organization_profile_version(
            session,
            tenant_id=t1,
            company_id=c1,
            version_id=version_id,
            membership=membership,
            access=None,
            at=datetime.now(UTC),
        )
        create_organization_profile_version(
            session,
            tenant_id=t1,
            company_id=c1,
            created_by=owner1,
            effective_from=date(2026, 6, 1),
            snapshot=_complete_snapshot(vat_status="special_rates_5_7"),
            change_reason="v2",
            at=datetime.now(UTC),
        )
        session.commit()

    with Session(migrated_database) as session:
        resolved = get_profile_for_period(
            session, tenant_id=t1, company_id=c1, period_month=date(2026, 6, 1)
        )
        assert resolved is not None
        assert resolved.period_confirmed is False

        with pytest.raises(AppError):
            list_versions_for_company(session, tenant_id=t1, company_id=c2)
        versions_t2 = list_versions_for_company(session, tenant_id=t2, company_id=c2)
        assert len(versions_t2) == 1


def test_assert_first_day_of_month() -> None:
    with pytest.raises(AppError):
        assert_first_day_of_month(date(2026, 1, 15))
