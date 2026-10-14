from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from app.domain.money import money

HORIZON_DAYS = 91
SCENARIOS = ("base", "conservative", "optimistic")
HAIRCUT = Decimal("0.80")
DELAY_DAYS = 7


@dataclass(frozen=True)
class PlanSlice:
    event_id: str
    direction: str
    residual: Decimal
    expected_date: date
    due_date: date
    confidence: str


@dataclass(frozen=True)
class Flow:
    day: date
    amount: Decimal
    direction: str
    event_id: str
    assumption: str


@dataclass(frozen=True)
class DayPoint:
    day: date
    opening: Decimal
    inflows: Decimal
    outflows: Decimal
    closing: Decimal


@dataclass(frozen=True)
class Projection:
    points: tuple[DayPoint, ...]
    flows: tuple[Flow, ...]
    gap_date: date | None
    gap_amount: Decimal


def project(
    opening: Decimal, as_of: date, events: tuple[PlanSlice, ...], scenario: str
) -> Projection:
    if scenario not in SCENARIOS:
        raise ValueError("unknown scenario")
    days = tuple(as_of + timedelta(days=offset) for offset in range(HORIZON_DAYS))
    allowed = set(days)
    incoming = {day: Decimal("0") for day in days}
    outgoing = {day: Decimal("0") for day in days}
    flows: list[Flow] = []
    for event in events:
        placed = _place(event, as_of, scenario)
        if placed is None:
            continue
        when, amount, assumption = placed
        if when not in allowed or amount <= 0:
            continue
        if event.direction == "in":
            incoming[when] += amount
        else:
            outgoing[when] += amount
        flows.append(Flow(when, amount, event.direction, event.event_id, assumption))
    balance = money(opening)
    points: list[DayPoint] = []
    first_gap: date | None = None
    worst: Decimal | None = None
    for day in days:
        close = money(balance + incoming[day] - outgoing[day])
        points.append(
            DayPoint(day, balance, money(incoming[day]), money(outgoing[day]), close)
        )
        if close < 0:
            if first_gap is None:
                first_gap = day
            if worst is None or close < worst:
                worst = close
        balance = close
    gap_amount = Decimal("0.00") if worst is None else money(-worst)
    return Projection(tuple(points), tuple(flows), first_gap, gap_amount)


def _place(event: PlanSlice, as_of: date, scenario: str) -> tuple[date, Decimal, str] | None:
    if event.residual <= 0:
        return None
    if event.direction == "in":
        return _inflow(event, as_of, scenario)
    return _outflow(event, as_of)


def _inflow(event: PlanSlice, as_of: date, scenario: str) -> tuple[date, Decimal, str] | None:
    if event.expected_date < as_of:
        return None
    if event.confidence == "tentative":
        if scenario != "optimistic":
            return None
        return event.expected_date, money(event.residual), "tentative_inflow"
    if event.confidence not in {"confirmed", "expected"}:
        return None
    if event.confidence == "expected" and scenario == "conservative":
        delayed = event.expected_date + timedelta(days=DELAY_DAYS)
        return delayed, money(event.residual * HAIRCUT), "conservative_haircut"
    return event.expected_date, money(event.residual), "residual"


def _outflow(event: PlanSlice, as_of: date) -> tuple[date, Decimal, str] | None:
    if event.confidence not in {"confirmed", "expected"}:
        return None
    if event.due_date < as_of or event.expected_date < as_of:
        return as_of, money(event.residual), "overdue_payable"
    return event.expected_date, money(event.residual), "residual"
