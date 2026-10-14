import uuid
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation

from app.config import Settings
from app.domain.alerts import (
    DEFAULT_COOLDOWN,
    coverage_is_stale,
    expense_hit,
    matched_horizon,
    median,
    revenue_hit,
    share_above,
)
from app.domain.billing.periods import MOSCOW
from app.domain.money import money, money_str
from app.errors import AppError
from app.models.cash import CashTransaction, TransferGroup
from app.models.identity import AuditLog, Company, Membership, User
from app.models.imports import ImportBatch, RawImportRow, SourceConnection
from app.models.signals import Alert, AlertRule
from app.security.access import BILLING_MANAGER, OPERATOR
from app.services.budget_service import plan_fact
from app.services.cash_service import company_summary, summary_payload
from app.services.forecast_service import company_forecast
from app.services.plan_service import slices_for
from app.services.wallet_service import open_company
from sqlalchemy import select
from sqlalchemy.orm import Session

DEFAULTS: dict[str, dict] = {
    "cash_gap": {
        "thresholds": {"horizons": [7, 14, 30, 90]},
        "severity": "high",
    },
    "reserve_breach": {"thresholds": {}, "severity": "high"},
    "expense_overrun": {
        "thresholds": {"amount": "50000.00", "percent": "15.00"},
        "severity": "warning",
    },
    "revenue_shortfall": {
        "thresholds": {"amount": "50000.00", "percent": "-15.00"},
        "severity": "warning",
    },
    "large_outgoing": {"thresholds": {"amount": "300000.00"}, "severity": "warning"},
    "unusual_outgoing": {
        "thresholds": {
            "amount": "50000.00",
            "multiple": "3",
            "baseline": 10,
            "window_days": 90,
        },
        "severity": "warning",
    },
    "new_counterparty": {"thresholds": {"amount": "100000.00"}, "severity": "warning"},
    "duplicate_candidate": {"thresholds": {}, "severity": "warning"},
    "stale_source": {"thresholds": {"lag_hours": 24}, "severity": "warning"},
    "overdue_obligation": {"thresholds": {}, "severity": "warning"},
    "unclassified_share": {"thresholds": {"percent": "10.00"}, "severity": "warning"},
}


class Finding:
    def __init__(self, rule_type: str, fingerprint: str, severity: str, evidence: dict, refs: list):
        self.rule_type = rule_type
        self.fingerprint = fingerprint
        self.severity = severity
        self.evidence = evidence
        self.refs = refs


def evaluate(session: Session, company: Company, report_date: date, at: datetime) -> dict:
    rules = _ensure_rules(session, company, at)
    by_type = {item.rule_type: item for item in rules}
    findings: list[Finding] = []
    skipped: list[dict] = []
    flags: list[str] = []
    _cash_signals(session, company, report_date, at, by_type, findings, flags)
    _budget_signals(session, company, report_date, by_type, findings)
    _payment_signals(session, company, report_date, by_type, findings, skipped)
    _source_signals(session, company, at, by_type, findings, flags)
    _overdue_signals(session, company, report_date, by_type, findings)
    _sync(session, company, findings, at)
    rows = session.scalars(
        select(Alert)
        .where(Alert.tenant_id == company.tenant_id, Alert.company_id == company.id)
        .order_by(Alert.first_seen_at)
    ).all()
    status = "preliminary" if flags else "ready"
    return {
        "report_date": report_date.isoformat(),
        "company_id": str(company.id),
        "status": status,
        "quality_flags": flags,
        "alerts": [_alert_payload(item) for item in rows],
        "skipped": skipped,
    }


def acknowledge(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    alert_id: uuid.UUID,
    at: datetime,
) -> dict:
    _deny(membership)
    row = session.get(Alert, alert_id)
    if row is None or row.tenant_id != membership.tenant_id:
        raise AppError(404, "not_found", "Сигнал не найден")
    open_company(session, user, row.company_id, settings, "write")
    if row.status == "resolved":
        raise AppError(422, "validation_error", "Снятый сигнал не подтверждается")
    if row.status == "open":
        row.status = "acknowledged"
        row.last_seen_at = at
    _audit(session, user, row.tenant_id, row.id, at)
    return _alert_payload(row)


def update_rule(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    company: Company,
    rule_type: str,
    *,
    thresholds: dict | None,
    enabled: bool | None,
    cooldown_minutes: int | None,
    at: datetime,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    if rule_type not in DEFAULTS:
        raise AppError(422, "validation_error", "Неизвестный тип сигнала")
    rules = _ensure_rules(session, company, at)
    row = next(item for item in rules if item.rule_type == rule_type)
    if thresholds is not None:
        row.thresholds_json = thresholds
    if enabled is not None:
        row.enabled = enabled
    if cooldown_minutes is not None:
        if cooldown_minutes < 0:
            raise AppError(422, "validation_error", "Пауза не может быть отрицательной")
        row.cooldown_minutes = cooldown_minutes
    row.updated_at = at
    return _rule_payload(row)


def _cash_signals(session, company, report_date, at, rules, findings, flags) -> None:
    moment = datetime.combine(report_date, time.max, tzinfo=MOSCOW)
    summary = summary_payload(company_summary(session, company, moment))
    if summary["available"] is None:
        _add_flag(flags, "missing_opening_balance")
    else:
        rule = _enabled(rules, "reserve_breach")
        headroom = summary["headroom"]
        if rule is not None and headroom is not None and Decimal(headroom) < 0:
            findings.append(
                Finding(
                    "reserve_breach",
                    f"reserve_breach:{company.id}",
                    rule.severity,
                    {
                        "formula": "headroom < 0",
                        "headroom": headroom,
                        "period": report_date.isoformat(),
                    },
                    [{"type": "company", "id": str(company.id)}],
                )
            )
    forecast = company_forecast(session, company, report_date, "base", at)
    if "missing_opening_balance" in forecast["quality_flags"]:
        _add_flag(flags, "missing_opening_balance")
    rule = _enabled(rules, "cash_gap")
    gap_date = forecast["gap_date"]
    gap_amount = forecast["gap_amount"]
    if rule is None or gap_date is None or gap_amount is None:
        return
    if Decimal(gap_amount) <= 0:
        return
    days = (date.fromisoformat(gap_date) - report_date).days
    horizons = _horizons(rule)
    horizon = matched_horizon(max(days, 0), horizons)
    if horizon is None:
        return
    findings.append(
        Finding(
            "cash_gap",
            f"cash_gap:{company.id}",
            rule.severity,
            {
                "formula": "closing < 0",
                "gap_date": gap_date,
                "gap_amount": gap_amount,
                "horizon_days": horizon,
                "as_of": report_date.isoformat(),
            },
            [{"type": "company", "id": str(company.id)}],
        )
    )


def _budget_signals(session, company, report_date, rules, findings) -> None:
    report = plan_fact(session, company, report_date)
    expense = _enabled(rules, "expense_overrun")
    revenue = _enabled(rules, "revenue_shortfall")
    for basis in report["bases"]:
        if basis["status"] != "ready":
            continue
        for line in basis["lines"]:
            if line["delta"] is None:
                continue
            delta = Decimal(line["delta"])
            percent = None if line["percent"] is None else Decimal(line["percent"])
            amount_limit = _money_rule(expense, "amount") if expense is not None else None
            percent_limit = _money_rule(expense, "percent") if expense is not None else None
            overrun = (
                expense is not None
                and amount_limit is not None
                and percent_limit is not None
                and line["metric_type"] == "cash_out"
                and line["character"] == "adverse"
                and expense_hit(delta, percent, amount_limit, percent_limit)
            )
            if overrun and expense is not None and amount_limit is not None:
                findings.append(_budget_finding(expense, "expense_overrun", line, report_date))
            if (
                revenue is not None
                and line["metric_type"] == "revenue"
                and line["character"] == "adverse"
                and revenue_hit(
                    delta, percent, _money_rule(revenue, "amount"), _money_rule(revenue, "percent")
                )
            ):
                findings.append(_budget_finding(revenue, "revenue_shortfall", line, report_date))


def _budget_finding(rule: AlertRule, rule_type: str, line: dict, report_date: date) -> Finding:
    return Finding(
        rule_type,
        f"{rule_type}:{line['line_id']}",
        rule.severity,
        {
            "formula": "fact - plan_to_date",
            "plan_to_date": line["plan_to_date"],
            "fact": line["fact"],
            "delta": line["delta"],
            "percent": line["percent"],
            "threshold": rule.thresholds_json,
            "period_from": line["period_from"],
            "period_to": line["period_to"],
            "report_date": report_date.isoformat(),
        },
        [{"type": "budget_line", "id": line["line_id"]}],
    )


def _payment_signals(session, company, report_date, rules, findings, skipped) -> None:
    rows = list(
        session.scalars(
            select(CashTransaction).where(
                CashTransaction.tenant_id == company.tenant_id,
                CashTransaction.company_id == company.id,
                CashTransaction.status == "posted",
                CashTransaction.business_date <= report_date,
            )
        ).all()
    )
    groups = {
        item.id: item
        for item in session.scalars(
            select(TransferGroup).where(TransferGroup.tenant_id == company.tenant_id)
        ).all()
    }
    external = [row for row in rows if row.direction == "out" and not _internal(row, groups)]
    large = _enabled(rules, "large_outgoing")
    if large is not None:
        limit = _money_rule(large, "amount")
        for row in external:
            if row.amount < limit:
                continue
            findings.append(
                Finding(
                    "large_outgoing",
                    f"large_outgoing:{row.id}",
                    large.severity,
                    {
                        "formula": "external out >= threshold",
                        "amount": money_str(row.amount),
                        "threshold": money_str(limit),
                        "business_date": row.business_date.isoformat(),
                    },
                    [{"type": "cash_transaction", "id": str(row.id)}],
                )
            )
    _unusual(external, rules, findings, skipped)
    _new_counterparty(external, rules, findings)
    _unclassified(external, report_date, rules, findings, company)


def _unusual(rows, rules, findings, skipped) -> None:
    rule = _enabled(rules, "unusual_outgoing")
    if rule is None:
        return
    limit = _money_rule(rule, "amount")
    multiple = _money_rule(rule, "multiple")
    baseline = int(rule.thresholds_json.get("baseline", 10))
    window = int(rule.thresholds_json.get("window_days", 90))
    for row in rows:
        if row.category_id is None or row.amount < limit:
            continue
        start = row.business_date.toordinal() - window
        prior = [
            item.amount
            for item in rows
            if item.id != row.id
            and item.category_id == row.category_id
            and item.business_date.toordinal() >= start
            and item.business_date < row.business_date
        ]
        if len(prior) < baseline:
            skipped.append(
                {
                    "type": "unusual_outgoing",
                    "reason": "insufficient_history",
                    "source_id": str(row.id),
                }
            )
            continue
        center = median(prior)
        if row.amount > center * multiple:
            findings.append(
                Finding(
                    "unusual_outgoing",
                    f"unusual_outgoing:{row.id}",
                    rule.severity,
                    {
                        "formula": "amount > multiple * median",
                        "amount": money_str(row.amount),
                        "median": money_str(center),
                        "multiple": money_str(multiple),
                        "baseline": len(prior),
                        "threshold": money_str(limit),
                        "business_date": row.business_date.isoformat(),
                    },
                    [{"type": "cash_transaction", "id": str(row.id)}],
                )
            )


def _new_counterparty(rows, rules, findings) -> None:
    rule = _enabled(rules, "new_counterparty")
    if rule is None:
        return
    limit = _money_rule(rule, "amount")
    first: dict[str, CashTransaction] = {}
    ordered = sorted(rows, key=lambda item: (item.business_date, item.created_at))
    for row in ordered:
        key = (row.counterparty_inn or row.counterparty_name or "").strip()
        if not key or key in first:
            continue
        first[key] = row
    for key, row in first.items():
        if row.amount < limit:
            continue
        findings.append(
            Finding(
                "new_counterparty",
                f"new_counterparty:{key}",
                rule.severity,
                {
                    "formula": "first external out >= threshold",
                    "amount": money_str(row.amount),
                    "threshold": money_str(limit),
                    "counterparty": key,
                    "business_date": row.business_date.isoformat(),
                },
                [{"type": "cash_transaction", "id": str(row.id)}],
            )
        )


def _unclassified(rows, report_date, rules, findings, company) -> None:
    rule = _enabled(rules, "unclassified_share")
    if rule is None:
        return
    start = date(report_date.year, report_date.month, 1)
    chosen = [row for row in rows if start <= row.business_date <= report_date]
    whole = money(sum((row.amount for row in chosen), Decimal("0")))
    part = money(sum((row.amount for row in chosen if row.category_id is None), Decimal("0")))
    limit = _money_rule(rule, "percent")
    percent = share_above(part, whole, limit)
    if percent is None:
        return
    findings.append(
        Finding(
            "unclassified_share",
            f"unclassified_share:{company.id}:{start.isoformat()}",
            rule.severity,
            {
                "formula": "unclassified external out / external out",
                "part": money_str(part),
                "whole": money_str(whole),
                "percent": money_str(percent),
                "threshold": money_str(limit),
                "period_from": start.isoformat(),
                "period_to": report_date.isoformat(),
            },
            [{"type": "company", "id": str(company.id)}],
        )
    )


def _source_signals(session, company, at, rules, findings, flags) -> None:
    rule = _enabled(rules, "stale_source")
    lag = 24 if rule is None else int(rule.thresholds_json.get("lag_hours", 24))
    sources = session.scalars(
        select(SourceConnection).where(
            SourceConnection.tenant_id == company.tenant_id,
            SourceConnection.company_id == company.id,
            SourceConnection.enabled.is_(True),
        )
    ).all()
    for source in sources:
        state = coverage_is_stale(source.coverage_through, at, lag)
        if state is None:
            _add_flag(flags, "missing_source_coverage")
            continue
        if rule is None or not state:
            continue
        covered = source.coverage_through.isoformat() if source.coverage_through else ""
        findings.append(
            Finding(
                "stale_source",
                f"stale_source:{source.id}",
                rule.severity,
                {
                    "formula": "business hours after coverage > lag",
                    "coverage_through": covered,
                    "lag_hours": lag,
                },
                [{"type": "source_connection", "id": str(source.id)}],
            )
        )
    duplicate = _enabled(rules, "duplicate_candidate")
    if duplicate is None:
        return
    ambiguous = session.scalars(
        select(RawImportRow)
        .join(ImportBatch, ImportBatch.id == RawImportRow.batch_id)
        .where(
            ImportBatch.tenant_id == company.tenant_id,
            ImportBatch.company_id == company.id,
            RawImportRow.duplicate_status == "ambiguous",
        )
    ).all()
    for row in ambiguous:
        findings.append(
            Finding(
                "duplicate_candidate",
                f"duplicate_candidate:{row.id}",
                duplicate.severity,
                {
                    "formula": "import row is ambiguous",
                    "row_number": row.row_number,
                    "external_id": row.external_id or "",
                },
                [{"type": "raw_import_row", "id": str(row.id)}],
            )
        )


def _overdue_signals(session, company, report_date, rules, findings) -> None:
    rule = _enabled(rules, "overdue_obligation")
    if rule is None:
        return
    for event, residual in slices_for(session, company):
        if residual <= 0 or event.due_date >= report_date:
            continue
        findings.append(
            Finding(
                "overdue_obligation",
                f"overdue_obligation:{event.id}",
                rule.severity,
                {
                    "formula": "residual > 0 and due_date < report_date",
                    "residual": money_str(residual),
                    "due_date": event.due_date.isoformat(),
                    "report_date": report_date.isoformat(),
                },
                [{"type": "planned_cash_event", "id": str(event.id)}],
            )
        )


def _sync(session: Session, company: Company, findings: list[Finding], at: datetime) -> None:
    existing = {
        row.fingerprint: row
        for row in session.scalars(
            select(Alert).where(
                Alert.tenant_id == company.tenant_id,
                Alert.company_id == company.id,
            )
        ).all()
    }
    seen: set[str] = set()
    for item in findings:
        seen.add(item.fingerprint)
        row = existing.get(item.fingerprint)
        if row is None:
            session.add(
                Alert(
                    tenant_id=company.tenant_id,
                    company_id=company.id,
                    rule_type=item.rule_type,
                    fingerprint=item.fingerprint,
                    severity=item.severity,
                    status="open",
                    first_seen_at=at,
                    last_seen_at=at,
                    evidence_json=item.evidence,
                    source_refs=item.refs,
                    resolved_at=None,
                )
            )
            continue
        row.last_seen_at = at
        row.evidence_json = item.evidence
        row.source_refs = item.refs
        row.severity = item.severity
        if row.status == "resolved":
            row.status = "open"
            row.resolved_at = None
    for row in existing.values():
        if row.fingerprint in seen or row.status == "resolved":
            continue
        row.status = "resolved"
        row.resolved_at = at
        row.last_seen_at = at
    session.flush()


def _ensure_rules(session: Session, company: Company, at: datetime) -> list[AlertRule]:
    rows = list(
        session.scalars(
            select(AlertRule).where(
                AlertRule.tenant_id == company.tenant_id,
                AlertRule.company_id == company.id,
            )
        ).all()
    )
    present = {item.rule_type for item in rows}
    for rule_type, spec in DEFAULTS.items():
        if rule_type in present:
            continue
        row = AlertRule(
            tenant_id=company.tenant_id,
            company_id=company.id,
            rule_type=rule_type,
            thresholds_json=spec["thresholds"],
            severity=spec["severity"],
            enabled=True,
            cooldown_minutes=DEFAULT_COOLDOWN,
            created_at=at,
            updated_at=at,
        )
        session.add(row)
        rows.append(row)
    session.flush()
    return rows


def _enabled(rules: dict[str, AlertRule], rule_type: str) -> AlertRule | None:
    row = rules.get(rule_type)
    if row is None or not row.enabled:
        return None
    return row


def _horizons(rule: AlertRule) -> list[int]:
    raw = rule.thresholds_json.get("horizons", [])
    if not isinstance(raw, list):
        return []
    return [int(item) for item in raw]


def _money_rule(rule: AlertRule, key: str) -> Decimal:
    try:
        return money(Decimal(str(rule.thresholds_json[key])))
    except (KeyError, InvalidOperation) as exc:
        raise AppError(422, "validation_error", "Некорректный порог") from exc


def _internal(row: CashTransaction, groups: dict[uuid.UUID, TransferGroup]) -> bool:
    if row.transfer_group_id is None:
        return False
    group = groups.get(row.transfer_group_id)
    return group is not None and group.kind == "internal" and group.status == "linked"


def _add_flag(flags: list[str], flag: str) -> None:
    if flag not in flags:
        flags.append(flag)


def _alert_payload(row: Alert) -> dict:
    resolved = None if row.resolved_at is None else row.resolved_at.isoformat()
    return {
        "id": str(row.id),
        "company_id": str(row.company_id),
        "type": row.rule_type,
        "severity": row.severity,
        "status": row.status,
        "fingerprint": row.fingerprint,
        "first_seen_at": row.first_seen_at.isoformat(),
        "last_seen_at": row.last_seen_at.isoformat(),
        "resolved_at": resolved,
        "evidence": row.evidence_json,
        "source_refs": row.source_refs,
    }


def _rule_payload(row: AlertRule) -> dict:
    return {
        "id": str(row.id),
        "type": row.rule_type,
        "thresholds": row.thresholds_json,
        "severity": row.severity,
        "enabled": row.enabled,
        "cooldown_minutes": row.cooldown_minutes,
    }


def _deny(membership: Membership) -> None:
    if membership.role in {OPERATOR, BILLING_MANAGER}:
        raise AppError(403, "forbidden", "Сигналы недоступны для этой роли")


def _audit(session, user, tenant_id, entity_id, at: datetime) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user.id,
            action="alert_acknowledged",
            entity_type="alert",
            entity_id=entity_id,
            before_redacted=None,
            after_redacted=None,
            request_id=None,
            created_at=at,
        )
    )
