import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app.config import Settings
from app.domain.budget import allocate_month, compare, metrics_for
from app.domain.money import money, money_str
from app.errors import AppError
from app.models.cash import CashCategory, CashTransaction, TransferGroup
from app.models.identity import AuditLog, Company, IdempotencyRecord, Membership, User
from app.models.revenue import Direction, RevenueEntry
from app.models.signals import BudgetDailyAllocation, BudgetLine, BudgetVersion
from app.security.access import BILLING_MANAGER, OPERATOR
from app.services.cash_service import request_hash
from app.services.wallet_service import open_company
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

CREATE_SCOPE = "budget-create"
APPROVE_SCOPE = "budget-approve"
DISTRIBUTION = "calendar_days"


def list_budgets(session: Session, company: Company) -> list[dict]:
    versions = session.scalars(
        select(BudgetVersion)
        .where(
            BudgetVersion.tenant_id == company.tenant_id,
            BudgetVersion.company_id == company.id,
        )
        .order_by(BudgetVersion.created_at)
    ).all()
    return [_version_payload(session, item) for item in versions]


def create_budget(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    *,
    name: str,
    year: int,
    basis: str,
    lines: list[dict],
    idempotency_key: str,
    at: datetime,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    fingerprint = request_hash(
        {"name": name, "year": year, "basis": basis, "lines": lines}
    )
    remembered = _idempotent(session, user, CREATE_SCOPE, idempotency_key, fingerprint)
    if remembered is not None:
        return remembered.response_body
    version = _insert_version(
        session, company, user, name=name, year=year, basis=basis, lines=lines, at=at
    )
    payload = _version_payload(session, version)
    _remember(
        session, user, company.tenant_id, CREATE_SCOPE, idempotency_key, fingerprint, payload, at
    )
    _audit(session, user, company.tenant_id, "budget_created", version.id, at)
    return payload


def replace_budget(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    version_id: uuid.UUID,
    *,
    lines: list[dict],
    at: datetime,
) -> dict:
    _deny(membership)
    current = _owned(session, membership, version_id)
    company = session.get(Company, current.company_id)
    if company is None:
        raise AppError(404, "not_found", "Фирма не найдена")
    open_company(session, user, company.id, settings, "write")
    if current.status == "draft":
        current.status = "archived"
        current.updated_at = at
    version = _insert_version(
        session,
        company,
        user,
        name=current.name,
        year=current.year,
        basis=current.basis,
        lines=lines,
        at=at,
    )
    _audit(session, user, company.tenant_id, "budget_revised", version.id, at)
    return _version_payload(session, version)


def approve_budget(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    version_id: uuid.UUID,
    *,
    idempotency_key: str,
    at: datetime,
) -> dict:
    _deny(membership)
    current = _owned(session, membership, version_id)
    company = session.get(Company, current.company_id)
    if company is None:
        raise AppError(404, "not_found", "Фирма не найдена")
    open_company(session, user, company.id, settings, "write")
    fingerprint = request_hash({"version_id": str(version_id)})
    remembered = _idempotent(session, user, APPROVE_SCOPE, idempotency_key, fingerprint)
    if remembered is not None:
        return remembered.response_body
    if current.status == "approved":
        payload = _version_payload(session, current)
    elif current.status != "draft":
        raise AppError(409, "conflict", "Утвердить можно только черновик")
    else:
        if not _lines(session, current):
            raise AppError(422, "validation_error", "В бюджете нет строк")
        previous = session.scalars(
            select(BudgetVersion).where(
                BudgetVersion.tenant_id == current.tenant_id,
                BudgetVersion.company_id == current.company_id,
                BudgetVersion.year == current.year,
                BudgetVersion.basis == current.basis,
                BudgetVersion.status == "approved",
                BudgetVersion.id != current.id,
            )
        ).all()
        for item in previous:
            item.status = "archived"
            item.approved_at = None
            item.updated_at = at
        current.status = "approved"
        current.approved_at = at
        current.updated_at = at
        try:
            session.flush()
        except IntegrityError as exc:
            raise AppError(409, "conflict", "Уже есть утверждённый бюджет") from exc
        payload = _version_payload(session, current)
    _remember(
        session, user, company.tenant_id, APPROVE_SCOPE, idempotency_key, fingerprint, payload, at
    )
    _audit(session, user, company.tenant_id, "budget_approved", current.id, at)
    return payload


def plan_fact(session: Session, company: Company, report_date: date) -> dict:
    flags: list[str] = []
    bases = []
    for basis in ("cash", "revenue"):
        block = _basis_block(session, company, report_date, basis)
        if block["status"] == "unavailable" and "missing_budget" not in flags:
            flags.append("missing_budget")
        bases.append(block)
    return {
        "report_date": report_date.isoformat(),
        "company_id": str(company.id),
        "quality_flags": flags,
        "bases": bases,
    }


def ensure_draft(
    session: Session,
    company: Company,
    user: User,
    *,
    year: int,
    basis: str,
    at: datetime,
) -> BudgetVersion:
    found = session.scalar(
        select(BudgetVersion)
        .where(
            BudgetVersion.tenant_id == company.tenant_id,
            BudgetVersion.company_id == company.id,
            BudgetVersion.year == year,
            BudgetVersion.basis == basis,
            BudgetVersion.status == "draft",
        )
        .order_by(BudgetVersion.created_at.desc())
    )
    if found is not None:
        return found
    version = BudgetVersion(
        tenant_id=company.tenant_id,
        company_id=company.id,
        name="Импорт",
        year=year,
        status="draft",
        basis=basis,
        approved_at=None,
        created_by=user.id,
        created_at=at,
        updated_at=at,
    )
    session.add(version)
    session.flush()
    return version


def add_line(
    session: Session,
    version: BudgetVersion,
    *,
    month: int,
    metric_type: str,
    amount: Decimal,
    category_id: uuid.UUID | None,
    direction_id: uuid.UUID | None,
) -> BudgetLine:
    _check_line(version.basis, month, metric_type, amount)
    line = BudgetLine(
        tenant_id=version.tenant_id,
        company_id=version.company_id,
        budget_version_id=version.id,
        month=month,
        category_id=category_id,
        direction_id=direction_id,
        metric_type=metric_type,
        amount=amount,
        distribution_method=DISTRIBUTION,
    )
    session.add(line)
    session.flush()
    _store_allocations(session, line, version.year, month, amount)
    return line


def revise_line(
    session: Session, line: BudgetLine, version: BudgetVersion, amount: Decimal
) -> None:
    if version.status != "draft":
        raise AppError(409, "conflict", "Утверждённый бюджет не переписывается")
    if amount < 0 or amount != money(amount):
        raise AppError(422, "validation_error", "Некорректная сумма")
    line.amount = amount
    _store_allocations(session, line, version.year, line.month, amount)


def _insert_version(
    session: Session,
    company: Company,
    user: User,
    *,
    name: str,
    year: int,
    basis: str,
    lines: list[dict],
    at: datetime,
) -> BudgetVersion:
    cleaned = name.strip()
    if not cleaned or len(cleaned) > 200:
        raise AppError(422, "validation_error", "Некорректное имя бюджета")
    if basis not in {"cash", "revenue"} or not 2000 <= year <= 2100:
        raise AppError(422, "validation_error", "Некорректные год или база")
    if not lines:
        raise AppError(422, "validation_error", "В бюджете нет строк")
    version = BudgetVersion(
        tenant_id=company.tenant_id,
        company_id=company.id,
        name=cleaned,
        year=year,
        status="draft",
        basis=basis,
        approved_at=None,
        created_by=user.id,
        created_at=at,
        updated_at=at,
    )
    session.add(version)
    session.flush()
    for item in lines:
        category_id = item.get("category_id")
        direction_id = item.get("direction_id")
        _category(session, company, category_id)
        _direction(session, company, direction_id)
        add_line(
            session,
            version,
            month=int(item["month"]),
            metric_type=str(item["metric_type"]),
            amount=_amount(str(item["amount"])),
            category_id=category_id,
            direction_id=direction_id,
        )
    return version


def _basis_block(session: Session, company: Company, report_date: date, basis: str) -> dict:
    version = session.scalar(
        select(BudgetVersion).where(
            BudgetVersion.tenant_id == company.tenant_id,
            BudgetVersion.company_id == company.id,
            BudgetVersion.year == report_date.year,
            BudgetVersion.basis == basis,
            BudgetVersion.status == "approved",
        )
    )
    empty: dict = {
        "basis": basis,
        "status": "unavailable",
        "version_id": None,
        "year": report_date.year,
        "lines": [],
    }
    if version is None:
        return empty
    rows = []
    for line in _lines(session, version):
        if date(version.year, line.month, 1) > report_date:
            continue
        rows.append(_line_fact(session, company, version, line, report_date))
    return {
        "basis": basis,
        "status": "ready",
        "version_id": str(version.id),
        "year": version.year,
        "lines": rows,
    }


def _line_fact(
    session: Session,
    company: Company,
    version: BudgetVersion,
    line: BudgetLine,
    report_date: date,
) -> dict:
    start = date(version.year, line.month, 1)
    end = report_date
    plan = _plan_to_date(session, line, start, end)
    section = _section(session, company, line.category_id)
    comparable, fact = _fact(session, company, version, line, start, end)
    base = {
        "line_id": str(line.id),
        "month": line.month,
        "metric_type": line.metric_type,
        "category_id": None if line.category_id is None else str(line.category_id),
        "direction_id": None if line.direction_id is None else str(line.direction_id),
        "period_from": start.isoformat(),
        "period_to": end.isoformat(),
        "plan_to_date": money_str(plan),
    }
    if not comparable or fact is None:
        return {
            **base,
            "fact": None,
            "delta": None,
            "percent": None,
            "status": "unavailable",
            "character": "unavailable",
        }
    view = compare(line.metric_type, plan, fact, section)
    return {
        **base,
        "fact": money_str(view.fact),
        "delta": money_str(view.delta),
        "percent": None if view.percent is None else money_str(view.percent),
        "status": view.status,
        "character": view.character,
    }


def _fact(
    session: Session,
    company: Company,
    version: BudgetVersion,
    line: BudgetLine,
    start: date,
    end: date,
) -> tuple[bool, Decimal | None]:
    if version.basis == "cash":
        return True, _cash_fact(session, company, line, start, end)
    return _revenue_fact(session, company, line, start, end)


def _cash_fact(
    session: Session, company: Company, line: BudgetLine, start: date, end: date
) -> Decimal:
    direction = "in" if line.metric_type == "cash_in" else "out"
    rows = session.scalars(
        select(CashTransaction).where(
            CashTransaction.tenant_id == company.tenant_id,
            CashTransaction.company_id == company.id,
            CashTransaction.status == "posted",
            CashTransaction.direction == direction,
            CashTransaction.business_date >= start,
            CashTransaction.business_date <= end,
        )
    ).all()
    groups = _groups(session, company)
    total = Decimal("0.00")
    for row in rows:
        if _internal(row, groups):
            continue
        if line.category_id is not None and row.category_id != line.category_id:
            continue
        total += row.amount
    return money(total)


def _revenue_fact(
    session: Session, company: Company, line: BudgetLine, start: date, end: date
) -> tuple[bool, Decimal | None]:
    rows = session.scalars(
        select(RevenueEntry).where(
            RevenueEntry.tenant_id == company.tenant_id,
            RevenueEntry.company_id == company.id,
            RevenueEntry.status == "posted",
            RevenueEntry.recognition_date >= start,
            RevenueEntry.recognition_date <= end,
        )
    ).all()
    chosen = [
        row
        for row in rows
        if line.direction_id is None or row.direction_id == line.direction_id
    ]
    if any(row.vat_basis != "net" or row.amount_ex_vat is None for row in chosen):
        return False, None
    total = Decimal("0.00")
    for row in chosen:
        signed = row.amount_ex_vat or Decimal("0.00")
        total += signed if row.entry_type == "sale" else -signed
    return True, money(total)


def _plan_to_date(session: Session, line: BudgetLine, start: date, end: date) -> Decimal:
    rows = session.scalars(
        select(BudgetDailyAllocation).where(
            BudgetDailyAllocation.tenant_id == line.tenant_id,
            BudgetDailyAllocation.line_id == line.id,
            BudgetDailyAllocation.allocation_date >= start,
            BudgetDailyAllocation.allocation_date <= end,
        )
    ).all()
    return money(sum((row.amount for row in rows), Decimal("0.00")))


def _store_allocations(
    session: Session, line: BudgetLine, year: int, month: int, amount: Decimal
) -> None:
    shares = allocate_month(year, month, amount)
    existing = {
        row.allocation_date: row
        for row in session.scalars(
            select(BudgetDailyAllocation).where(
                BudgetDailyAllocation.tenant_id == line.tenant_id,
                BudgetDailyAllocation.line_id == line.id,
            )
        ).all()
    }
    for day, share in shares:
        found = existing.get(day)
        if found is None:
            session.add(
                BudgetDailyAllocation(
                    tenant_id=line.tenant_id,
                    line_id=line.id,
                    allocation_date=day,
                    amount=share,
                )
            )
        else:
            found.amount = share
    session.flush()


def _version_payload(session: Session, version: BudgetVersion) -> dict:
    lines = []
    for line in _lines(session, version):
        allocated = session.scalars(
            select(BudgetDailyAllocation.amount).where(
                BudgetDailyAllocation.line_id == line.id
            )
        ).all()
        total = money(sum((item for item in allocated if isinstance(item, Decimal)), Decimal(0)))
        lines.append(
            {
                "id": str(line.id),
                "month": line.month,
                "metric_type": line.metric_type,
                "amount": money_str(line.amount),
                "allocated_total": money_str(total),
                "category_id": None if line.category_id is None else str(line.category_id),
                "direction_id": None if line.direction_id is None else str(line.direction_id),
                "distribution_method": line.distribution_method,
            }
        )
    approved = None if version.approved_at is None else version.approved_at.isoformat()
    return {
        "id": str(version.id),
        "company_id": str(version.company_id),
        "name": version.name,
        "year": version.year,
        "basis": version.basis,
        "status": version.status,
        "approved_at": approved,
        "lines": lines,
    }


def _lines(session: Session, version: BudgetVersion) -> list[BudgetLine]:
    return list(
        session.scalars(
            select(BudgetLine)
            .where(BudgetLine.budget_version_id == version.id)
            .order_by(BudgetLine.month, BudgetLine.metric_type)
        ).all()
    )


def _groups(session: Session, company: Company) -> dict[uuid.UUID, TransferGroup]:
    rows = session.scalars(
        select(TransferGroup).where(TransferGroup.tenant_id == company.tenant_id)
    ).all()
    return {row.id: row for row in rows}


def _internal(row: CashTransaction, groups: dict[uuid.UUID, TransferGroup]) -> bool:
    if row.transfer_group_id is None:
        return False
    group = groups.get(row.transfer_group_id)
    return group is not None and group.kind == "internal" and group.status == "linked"


def _section(session: Session, company: Company, category_id: uuid.UUID | None) -> str | None:
    if category_id is None:
        return None
    category = session.get(CashCategory, category_id)
    if category is None or category.tenant_id != company.tenant_id:
        return None
    return category.cash_flow_section


def _check_line(basis: str, month: int, metric: str, amount: Decimal) -> None:
    if month < 1 or month > 12 or metric not in metrics_for(basis):
        raise AppError(422, "validation_error", "Строка не соответствует базе бюджета")
    if amount < 0:
        raise AppError(422, "validation_error", "Сумма бюджета не может быть отрицательной")


def _amount(raw: str) -> Decimal:
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise AppError(422, "validation_error", "Некорректная сумма") from exc
    if value != money(value) or value < 0:
        raise AppError(
            422, "validation_error", "Сумма бюджета должна быть до копейки и не меньше нуля"
        )
    return money(value)


def _category(session: Session, company: Company, category_id: uuid.UUID | None) -> None:
    if category_id is None:
        return
    category = session.get(CashCategory, category_id)
    if category is None or category.tenant_id != company.tenant_id:
        raise AppError(422, "validation_error", "Неизвестная категория")


def _direction(session: Session, company: Company, direction_id: uuid.UUID | None) -> None:
    if direction_id is None:
        return
    direction = session.get(Direction, direction_id)
    if (
        direction is None
        or direction.tenant_id != company.tenant_id
        or direction.company_id != company.id
    ):
        raise AppError(422, "validation_error", "Неизвестное направление")


def _owned(session: Session, membership: Membership, version_id: uuid.UUID) -> BudgetVersion:
    row = session.get(BudgetVersion, version_id)
    if row is None or row.tenant_id != membership.tenant_id:
        raise AppError(404, "not_found", "Бюджет не найден")
    return row


def _deny(membership: Membership) -> None:
    if membership.role in {OPERATOR, BILLING_MANAGER}:
        raise AppError(403, "forbidden", "Бюджет недоступен для этой роли")


def _audit(session, user, tenant_id, action: str, entity_id, at: datetime) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user.id,
            action=action,
            entity_type="budget_version",
            entity_id=entity_id,
            before_redacted=None,
            after_redacted=None,
            request_id=None,
            created_at=at,
        )
    )


def _idempotent(session, user, scope: str, key: str, fingerprint: str):
    row = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if row is None:
        return None
    if row.request_hash != fingerprint:
        raise AppError(409, "idempotency_conflict", "Другой payload для того же ключа")
    return row


def _remember(session, user, tenant_id, scope, key, fingerprint, payload, at) -> None:
    session.add(
        IdempotencyRecord(
            tenant_id=tenant_id,
            user_id=user.id,
            scope=scope,
            idempotency_key=key,
            request_hash=fingerprint,
            status_code=200,
            response_body=payload,
            created_at=at,
        )
    )
