import uuid
from datetime import date, datetime, time
from decimal import Decimal

from app.domain.billing.periods import MOSCOW
from app.domain.forecast import HORIZON_DAYS, SCENARIOS, PlanSlice, project
from app.domain.money import money_str
from app.domain.revenue import input_revision
from app.errors import AppError
from app.models.identity import Company
from app.models.plan import ForecastContribution, ForecastPoint, ForecastRun
from app.services.cash_service import company_summary, summary_payload
from app.services.plan_service import slices_for
from sqlalchemy import select
from sqlalchemy.orm import Session


def company_forecast(
    session: Session, company: Company, as_of: date, scenario: str, at: datetime
) -> dict:
    if scenario not in SCENARIOS:
        raise AppError(422, "validation_error", "Неизвестный сценарий")
    opening, flags = _opening(session, company, as_of)
    pairs = slices_for(session, company)
    parts = {
        "as_of": as_of.isoformat(),
        "scenario": scenario,
        "opening": "" if opening is None else money_str(opening),
        "events": "|".join(
            f"{row.id}:{money_str(residual)}:{row.expected_date}:{row.due_date}:"
            f"{row.confidence}:{row.direction}"
            for row, residual in sorted(pairs, key=lambda item: str(item[0].id))
        ),
    }
    revision = input_revision(parts)
    status = "preliminary" if opening is None else "ready"
    existing = _current(session, company, as_of, scenario)
    if existing is not None and existing.input_revision == revision and existing.status == status:
        return _payload(session, existing, company)
    if existing is not None:
        existing.status = "stale"
    run = ForecastRun(
        tenant_id=company.tenant_id,
        company_id=company.id,
        as_of=as_of,
        scenario=scenario,
        horizon_days=HORIZON_DAYS,
        input_revision=revision,
        status=status,
        quality_flags=flags,
        opening_amount=opening,
        gap_date=None,
        gap_amount=None,
        created_at=at,
    )
    session.add(run)
    session.flush()
    if opening is None:
        return _payload(session, run, company)
    view = project(
        opening,
        as_of,
        tuple(
            PlanSlice(
                str(row.id),
                row.direction,
                residual,
                row.expected_date,
                row.due_date,
                row.confidence,
            )
            for row, residual in pairs
            if residual > 0
        ),
        scenario,
    )
    run.gap_date = view.gap_date
    run.gap_amount = view.gap_amount
    for point in view.points:
        session.add(
            ForecastPoint(
                tenant_id=company.tenant_id,
                run_id=run.id,
                point_date=point.day,
                opening_amount=point.opening,
                inflows=point.inflows,
                outflows=point.outflows,
                closing_amount=point.closing,
            )
        )
    for flow in view.flows:
        session.add(
            ForecastContribution(
                tenant_id=company.tenant_id,
                run_id=run.id,
                point_date=flow.day,
                source_type="planned_event",
                source_id=uuid.UUID(flow.event_id),
                amount=flow.amount,
                direction=flow.direction,
                assumption=flow.assumption,
            )
        )
    session.flush()
    return _payload(session, run, company)


def group_forecast(
    session: Session, companies: list[Company], as_of: date, scenario: str, at: datetime
) -> dict:
    rows = [company_forecast(session, company, as_of, scenario, at) for company in companies]
    known = [item for item in rows if item["opening"] is not None]
    group_opening = None
    if rows and len(known) == len(rows):
        total = sum((Decimal(item["opening"]) for item in known), Decimal("0"))
        group_opening = money_str(total)
    status = "ready" if group_opening is not None else "preliminary"
    return {
        "as_of": as_of.isoformat(),
        "scenario": scenario,
        "status": status,
        "scope_company_ids": [str(company.id) for company in companies],
        "group_opening": group_opening,
        "company_risks": [
            {
                "company_id": item["company_id"],
                "gap_date": item["gap_date"],
                "gap_amount": item["gap_amount"],
                "status": item["status"],
            }
            for item in rows
        ],
    }


def _opening(session: Session, company: Company, as_of: date) -> tuple[Decimal | None, list[str]]:
    moment = datetime.combine(as_of, time.max, tzinfo=MOSCOW)
    summary = summary_payload(company_summary(session, company, moment))
    flags: list[str] = []
    if summary["available"] is None:
        flags.append("missing_opening_balance")
        return None, flags
    return Decimal(summary["available"]), flags


def _current(session: Session, company: Company, as_of: date, scenario: str) -> ForecastRun | None:
    return session.scalar(
        select(ForecastRun)
        .where(
            ForecastRun.tenant_id == company.tenant_id,
            ForecastRun.company_id == company.id,
            ForecastRun.as_of == as_of,
            ForecastRun.scenario == scenario,
            ForecastRun.horizon_days == HORIZON_DAYS,
            ForecastRun.status != "stale",
        )
        .order_by(ForecastRun.created_at.desc())
    )


def _payload(session: Session, run: ForecastRun, company: Company) -> dict:
    points = session.scalars(
        select(ForecastPoint)
        .where(ForecastPoint.run_id == run.id)
        .order_by(ForecastPoint.point_date)
    ).all()
    contributions = session.scalars(
        select(ForecastContribution)
        .where(ForecastContribution.run_id == run.id)
        .order_by(ForecastContribution.point_date)
    ).all()
    return {
        "company_id": str(company.id),
        "as_of": run.as_of.isoformat(),
        "scenario": run.scenario,
        "horizon_days": run.horizon_days,
        "status": run.status,
        "input_revision": run.input_revision,
        "quality_flags": list(run.quality_flags),
        "opening": None if run.opening_amount is None else money_str(run.opening_amount),
        "gap_date": None if run.gap_date is None else run.gap_date.isoformat(),
        "gap_amount": None if run.gap_amount is None else money_str(run.gap_amount),
        "points": [
            {
                "date": item.point_date.isoformat(),
                "opening": money_str(item.opening_amount),
                "inflows": money_str(item.inflows),
                "outflows": money_str(item.outflows),
                "closing": money_str(item.closing_amount),
            }
            for item in points
        ],
        "contributions": [
            {
                "date": item.point_date.isoformat(),
                "source_type": item.source_type,
                "source_id": str(item.source_id),
                "amount": money_str(item.amount),
                "direction": item.direction,
                "assumption": item.assumption,
            }
            for item in contributions
        ],
    }
