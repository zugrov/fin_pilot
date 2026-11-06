from datetime import date

from app.api.deps import DbSession, current_session
from app.errors import AppError
from app.services.tax_norms_service import get_version_for_date, version_to_payload
from fastapi import APIRouter, Request

router = APIRouter(prefix="/tax-norms", tags=["tax-norms"])


@router.get("/current")
def get_current_norms(
    request: Request,
    session: DbSession,
    as_of: date,
) -> dict:
    """
    Действующая версия справочника на дату (общая, не при tenant).
    Только для аутентифицированного пользователя; записи нет.
    """
    _row, _user = current_session(request, session)
    version = get_version_for_date(session, as_of)
    if version is None:
        raise AppError(404, "not_found", "Нет версии норм на указанную дату")
    return version_to_payload(version)
