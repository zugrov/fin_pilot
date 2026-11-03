"""Read-only сверка с 1С (FA-R03.2), только локальная dev/test среда."""

from __future__ import annotations

from uuid import UUID

from app.api.deps import DbSession, current_session, settings_of
from app.clock import now
from app.errors import AppError
from app.security.access import assert_finance_access, find_company_across_memberships
from app.services.bank_card_reconciliation_service import report_for_company_local
from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter(tags=["reconciliation"])


def _local_reconciliation_or_404(settings, company_id: UUID) -> None:
    if not settings.fa_r03_local_reconciliation_active():
        raise HTTPException(status_code=404, detail="Not Found")
    allowed = settings.fa_r03_local_reconciliation_company_id.strip()
    if str(company_id) != allowed:
        raise HTTPException(status_code=404, detail="Not Found")


@router.get("/companies/{company_id}/reconciliation/bank-card-51")
def get_bank_card51_reconciliation(
    request: Request,
    session: DbSession,
    company_id: UUID,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
) -> dict:
    """Сверка ClientBank ↔ карточка 51 без записи в БД; без текстов назначений."""
    settings = settings_of(request)
    _local_reconciliation_or_404(settings, company_id)

    _row, user = current_session(request, session)
    membership, company = find_company_across_memberships(session, user.id, company_id)
    assert_finance_access(
        session,
        membership=membership,
        company=company,
        user_verified=user.email_verified_at is not None,
        at=now(),
        mode="read",
        grace_days=settings.billing_grace_days,
        bypass=settings.billing_bypass_allowed(),
    )

    try:
        return report_for_company_local(
            samples_root=settings.fa_r03_local_samples_root.strip(),
            year=year,
            month=month,
        )
    except AppError:
        raise
    except OSError as exc:
        raise AppError(503, "unavailable", "не удалось прочитать локальные образцы") from exc
