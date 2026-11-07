import uuid
from datetime import UTC, date, datetime

import pytest
from app.domain.org_profile.validation import ProfileSnapshot
from app.errors import AppError
from app.models.identity import CompanyAccess, Membership
from app.models.org_profile import OrganizationProfileVersion
from app.services.org_profile_service import (
    assert_first_day_of_month,
    assert_profile_fields_immutable,
    confirm_organization_profile_version,
    create_organization_profile_version,
    get_profile_for_period,
    list_versions_for_company,
)
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from tests.integration.balances_test_util import assert_finpilot_test_database


@pytest.fixture(autouse=True)
def _guard_db(migrated_database):
    assert_finpilot_test_database(migrated_database)


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


def test_create_version_validates_usn(migrated_database) -> None:
    tenant_id, company_id, owner_id = _seed_company(migrated_database)
    snap = ProfileSnapshot(tax_system="usn", usn_tax_object="income")
    with Session(migrated_database) as session:
        with pytest.raises(AppError) as exc:
            create_organization_profile_version(
                session,
                tenant_id=tenant_id,
                company_id=company_id,
                created_by=owner_id,
                effective_from=date(2026, 2, 15),
                snapshot=snap,
                change_reason="bad date",
                at=datetime.now(UTC),
            )
        assert exc.value.code == "invalid_effective_from"


def test_create_and_confirm_version(migrated_database) -> None:
    tenant_id, company_id, owner_id = _seed_company(migrated_database)
    snap = ProfileSnapshot(
        tax_system="usn",
        usn_tax_object="income",
        org_form="ooo",
        accounting_source="onec",
    )
    at = datetime(2026, 5, 1, tzinfo=UTC)
    with Session(migrated_database) as session:
        row = create_organization_profile_version(
            session,
            tenant_id=tenant_id,
            company_id=company_id,
            created_by=owner_id,
            effective_from=date(2026, 6, 1),
            snapshot=snap,
            change_reason="setup",
            at=at,
        )
        session.commit()
        version_id = row.id

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


def test_confirm_rejects_non_owner_accountant(migrated_database) -> None:
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


def test_confirm_not_latest_rejected(migrated_database) -> None:
    tenant_id, company_id, owner_id = _seed_company(migrated_database)
    snap = ProfileSnapshot(tax_system="usn", usn_tax_object="income", org_form="ooo")
    with Session(migrated_database) as session:
        bootstrap = session.scalar(
            select(OrganizationProfileVersion).where(
                OrganizationProfileVersion.company_id == company_id
            )
        )
        create_organization_profile_version(
            session,
            tenant_id=tenant_id,
            company_id=company_id,
            created_by=owner_id,
            effective_from=date(2026, 4, 1),
            snapshot=snap,
            change_reason="newer",
            at=datetime.now(UTC),
        )
        membership = _membership(session, tenant_id, owner_id)
        with pytest.raises(AppError) as exc:
            confirm_organization_profile_version(
                session,
                tenant_id=tenant_id,
                company_id=company_id,
                version_id=bootstrap.id,
                membership=membership,
                access=None,
                at=datetime.now(UTC),
            )
        assert exc.value.code == "not_latest_version"


def test_profile_resolution_and_isolation(migrated_database) -> None:
    t1, c1, _ = _seed_company(migrated_database, tenant_name="t1")
    t2, c2, _ = _seed_company(migrated_database, tenant_name="t2")
    snap = ProfileSnapshot(tax_system="usn", usn_tax_object="income", org_form="ooo")
    with Session(migrated_database) as session:
        create_organization_profile_version(
            session,
            tenant_id=t1,
            company_id=c1,
            created_by=uuid.uuid4(),
            effective_from=date(2026, 2, 1),
            snapshot=snap,
            change_reason="v2",
            at=datetime.now(UTC),
        )
        session.commit()

    with Session(migrated_database) as session:
        resolved = get_profile_for_period(
            session, tenant_id=t1, company_id=c1, period_month=date(2026, 2, 1)
        )
        assert resolved is not None
        assert resolved.period_confirmed is False

        with pytest.raises(AppError):
            list_versions_for_company(session, tenant_id=t1, company_id=c2)
        versions_t2 = list_versions_for_company(session, tenant_id=t2, company_id=c2)
        assert len(versions_t2) == 1
        assert versions_t2[0].tenant_id == t2


def test_immutable_profile_fields() -> None:
    row = OrganizationProfileVersion(
        tenant_id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        effective_from=date(2026, 1, 1),
        org_form="unspecified",
        tax_system="unspecified",
        usn_tax_object="unspecified",
        vat_status="unknown",
        prices_include_vat="unknown",
        revenue_recognition_method="unknown",
        accounting_source="unspecified",
        industry_sphere="unspecified",
        money_channels=["unspecified"],
        prior_year_revenue_band="unknown",
        month_close_policy="unknown",
        created_at=datetime.now(UTC),
    )
    with pytest.raises(AppError) as exc:
        assert_profile_fields_immutable(row, attempted_field="tax_system")
    assert exc.value.code == "immutable_profile_version"


def test_assert_first_day_of_month() -> None:
    with pytest.raises(AppError):
        assert_first_day_of_month(date(2026, 1, 15))
