import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from app.config import Settings
from app.domain.money import money, money_str
from app.domain.telegram_text import (
    SlotState,
    content_hash,
    escape_html,
    in_quiet,
    materiality_worsened,
    slot_state,
    split_parts,
)
from app.errors import AppError
from app.models.cash import CashTransaction, TransferGroup
from app.models.identity import Company, Membership, User
from app.models.imports import SourceConnection
from app.models.signals import AlertRule
from app.models.telegram import (
    DigestSnapshot,
    DigestSubscription,
    NotificationOutbox,
    TelegramBinding,
)
from app.security.access import assert_finance_access
from app.security.context import set_context
from app.services import alert_service, budget_service, forecast_service
from app.services.cash_service import company_summary, summary_payload
from app.services.plan_service import slices_for
from app.services.report_service import revenue_snapshot
from app.services.telegram_binding import load_companies, zone_of
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

SEVERITY = {"critical": 0, "high": 1, "warning": 2, "info": 3}
MAGNITUDE = {
    "cash_gap": "gap_amount",
    "reserve_breach": "headroom",
    "expense_overrun": "delta",
    "revenue_shortfall": "delta",
    "large_outgoing": "amount",
    "unusual_outgoing": "amount",
    "new_counterparty": "amount",
    "unclassified_share": "percent",
    "overdue_obligation": "residual",
}
HIDDEN = {"counterparty_name", "counterparty_inn", "description", "purpose", "inn"}


def schedule_digests(session: Session, settings: Settings, at: datetime) -> int:
    created = 0
    rows = session.execute(text("SELECT * FROM app_list_digest_subscriptions()")).mappings().all()
    for row in rows:
        set_context(
            session,
            tenant_id=row["subscription_tenant_id"],
            user_id=row["subscription_user_id"],
        )
        subscription = session.get(DigestSubscription, row["subscription_id"])
        if subscription is None or not subscription.enabled:
            continue
        state, local_date = slot_state(
            at,
            subscription.local_time,
            subscription.timezone,
            [int(item) for item in subscription.days_of_week],
        )
        if subscription.last_scheduled_for == local_date or state in {
            SlotState.WAITING,
            SlotState.CLOSED,
        }:
            continue
        if state == SlotState.MISSED:
            subscription.last_scheduled_for = local_date
            subscription.updated_at = at
            continue
        if _create_scheduled(session, settings, subscription, local_date, at):
            created += 1
    consider_urgent(session, settings, at)
    return created


def preview_text(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    at: datetime,
) -> dict:
    subscription = _require_subscription(session, membership, user)
    report = _report_date(subscription, at)
    metrics = _metrics(session, membership, user, settings, subscription, report, at)
    parts = render_parts(metrics, settings.public_base_url)
    return {"text": "\n\n".join(parts), "sent": False, "content_hash": content_hash(metrics)}


def queue_manual(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    *,
    request_id: str,
    at: datetime,
) -> DigestSnapshot:
    subscription = _require_subscription(session, membership, user)
    binding = session.get(TelegramBinding, subscription.binding_id)
    if binding is None or binding.status != "active":
        raise AppError(404, "not_found", "Активная привязка не найдена")
    report = _report_date(subscription, at)
    zone = zone_of(subscription.timezone)
    local_date = at.astimezone(zone).date()
    return _store_snapshot(
        session,
        settings,
        subscription,
        binding,
        kind="manual",
        request_id=request_id,
        local_date=local_date,
        report_date=report,
        at=at,
    )


def consider_urgent(session: Session, settings: Settings, at: datetime) -> int:
    created = 0
    rows = session.execute(text("SELECT * FROM app_list_digest_subscriptions()")).mappings().all()
    for row in rows:
        set_context(
            session,
            tenant_id=row["subscription_tenant_id"],
            user_id=row["subscription_user_id"],
        )
        subscription = session.get(DigestSubscription, row["subscription_id"])
        binding = None
        if subscription is not None:
            binding = session.get(TelegramBinding, subscription.binding_id)
        if subscription is None or binding is None or not subscription.instant_alerts:
            continue
        if not subscription.enabled or binding.status != "active":
            continue
        zone = zone_of(subscription.timezone)
        local = at.astimezone(zone).timetz().replace(tzinfo=None)
        if in_quiet(local, subscription.quiet_start, subscription.quiet_end):
            continue
        user = session.get(User, subscription.user_id)
        membership = _membership(session, subscription)
        if user is None or membership is None:
            continue
        report = _report_date(subscription, at)
        for company in load_companies(session, membership, subscription.company_scope):
            if not _can_read(session, membership, company, user, settings, at):
                continue
            evaluated = alert_service.evaluate(session, company, report, at)
            for item in evaluated["alerts"]:
                if item["status"] not in {"open", "acknowledged"}:
                    continue
                if _enqueue_urgent(session, subscription, binding, item, at):
                    created += 1
    return created


def render_parts(metrics: dict, base_url: str) -> list[str]:
    blocks = _blocks(metrics)
    parts = split_parts(blocks)
    if not parts:
        parts = ["Сводка без показателей."]
    _ = base_url
    return parts


def message_buttons(base_url: str) -> list[dict]:
    root = base_url.rstrip("/")
    return [
        {"label": "Фирмы", "url": f"{root}/overview"},
        {"label": "Календарь", "url": f"{root}/calendar"},
        {"label": "Прогноз", "url": f"{root}/forecast"},
    ]


def _create_scheduled(session, settings, subscription, local_date: date, at: datetime) -> bool:
    lock_key = subscription.id.int % (2**62)
    session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    existing = session.scalar(
        select(DigestSnapshot).where(
            DigestSnapshot.subscription_id == subscription.id,
            DigestSnapshot.local_date == local_date,
            DigestSnapshot.kind == "scheduled",
        )
    )
    subscription.last_scheduled_for = local_date
    subscription.updated_at = at
    if existing is not None:
        return False
    binding = session.get(TelegramBinding, subscription.binding_id)
    if binding is None or binding.status != "active":
        return False
    report = local_date - timedelta(days=1)
    try:
        with session.begin_nested():
            _store_snapshot(
                session,
                settings,
                subscription,
                binding,
                kind="scheduled",
                request_id=None,
                local_date=local_date,
                report_date=report,
                at=at,
            )
    except IntegrityError:
        return False
    return True


def _store_snapshot(
    session,
    settings,
    subscription: DigestSubscription,
    binding: TelegramBinding,
    *,
    kind: str,
    request_id: str | None,
    local_date: date,
    report_date: date,
    at: datetime,
) -> DigestSnapshot:
    user = session.get(User, subscription.user_id)
    membership = _membership(session, subscription)
    if user is None or membership is None:
        raise AppError(404, "not_found", "Подписка не найдена")
    metrics = _metrics(session, membership, user, settings, subscription, report_date, at)
    digest = content_hash(metrics)
    zone = zone_of(subscription.timezone)
    snapshot = DigestSnapshot(
        tenant_id=subscription.tenant_id,
        subscription_id=subscription.id,
        kind=kind,
        request_id=request_id,
        local_date=local_date,
        report_date=report_date,
        scheduled_for=at,
        as_of=datetime.combine(report_date, time.max, tzinfo=zone),
        company_ids=list(metrics["company_ids"]),
        metrics_json=metrics,
        quality_json={"flags": metrics["quality_flags"]},
        content_hash=digest,
        status="ready",
        created_at=at,
    )
    session.add(snapshot)
    session.flush()
    _enqueue_parts(session, snapshot, binding, settings, at)
    return snapshot


def _enqueue_parts(
    session, snapshot: DigestSnapshot, binding: TelegramBinding, settings, at
) -> None:
    parts = render_parts(snapshot.metrics_json, settings.public_base_url)
    buttons = message_buttons(settings.public_base_url)
    for number, part_text in enumerate(parts, start=1):
        session.add(
            NotificationOutbox(
                tenant_id=snapshot.tenant_id,
                snapshot_id=snapshot.id,
                alert_id=None,
                binding_id=binding.id,
                part_number=number,
                materiality="",
                payload={
                    "text": part_text,
                    "parse_mode": "HTML",
                    "protect_content": True,
                    "content_hash": snapshot.content_hash,
                    "alerts": snapshot.metrics_json.get("alerts", []),
                    "company_ids": snapshot.company_ids,
                    "buttons": buttons if number == len(parts) else [],
                },
                status="pending",
                attempts=0,
                next_attempt_at=at,
                telegram_message_id=None,
                last_error=None,
                lease_until=None,
                created_at=at,
                sent_at=None,
            )
        )
    session.flush()


def _enqueue_urgent(session, subscription, binding, item: dict, at: datetime) -> bool:
    current = _magnitude(item)
    if current is None:
        return False
    previous, sent_at = _previous_materiality(session, subscription.tenant_id, item["id"])
    if previous is None or sent_at is None:
        return False
    if not materiality_worsened(previous, current):
        return False
    cooldown = _cooldown(session, item)
    if sent_at + timedelta(minutes=cooldown) > at:
        return False
    level = money_str(current)
    text = (
        f"{escape_html(item['type'])}: {money_str(previous)} → {level}. "
        "Повтор сигнала после ухудшения. Подтверждение условие не снимает."
    )
    try:
        with session.begin_nested():
            session.add(
                NotificationOutbox(
                    tenant_id=subscription.tenant_id,
                    snapshot_id=None,
                    alert_id=uuid.UUID(item["id"]),
                    binding_id=binding.id,
                    part_number=1,
                    materiality=level,
                    payload={
                        "text": text,
                        "parse_mode": "HTML",
                        "protect_content": True,
                        "alert_id": item["id"],
                        "materiality": level,
                        "company_ids": [item["company_id"]],
                        "buttons": [],
                    },
                    status="pending",
                    attempts=0,
                    next_attempt_at=at,
                    telegram_message_id=None,
                    last_error=None,
                    lease_until=None,
                    created_at=at,
                    sent_at=None,
                )
            )
            session.flush()
    except IntegrityError:
        return False
    return True


def _metrics(
    session, membership, user, settings, subscription, report_date: date, at: datetime
) -> dict:
    zone = zone_of(subscription.timezone)
    moment = datetime.combine(report_date, time.max, tzinfo=zone)
    cards = []
    flags: list[str] = []
    for company in load_companies(session, membership, subscription.company_scope):
        if not _can_read(session, membership, company, user, settings, at):
            flags.append("partial_scope")
            continue
        cards.append(
            _company_card(
                session, company, report_date, moment, at, subscription.privacy_level
            )
        )
    partial = "partial_scope" in flags or any(card["cash_total"] is None for card in cards)
    if partial and "partial_scope" not in flags:
        flags.append("partial_aggregate")
    totals = _totals(cards, partial)
    alerts = [item for card in cards for item in card["alerts"]]
    alerts.sort(key=lambda item: SEVERITY.get(item["severity"], 9))
    return {
        "report_date": report_date.isoformat(),
        "formed_at": at.isoformat(),
        "timezone": subscription.timezone,
        "mode": subscription.mode,
        "privacy": subscription.privacy_level,
        "partial": partial,
        "quality_flags": flags,
        "company_ids": [card["company_id"] for card in cards],
        "totals": totals,
        "companies": cards,
        "alerts": alerts[:3],
        "alert_count": len(alerts),
    }


def _company_card(
    session, company: Company, report_date: date, moment: datetime, at, privacy: str
) -> dict:
    summary = summary_payload(company_summary(session, company, moment))
    forecast = forecast_service.company_forecast(session, company, report_date, "base", at)
    month_start = report_date.replace(day=1)
    revenue_day = revenue_snapshot(
        session, company.id, company.tenant_id, (report_date, report_date)
    )
    revenue_mtd = revenue_snapshot(
        session, company.id, company.tenant_id, (month_start, report_date)
    )
    plan = budget_service.plan_fact(session, company, report_date)
    evaluated = alert_service.evaluate(session, company, report_date, at)
    incoming, outgoing = _day_flows(session, company, report_date)
    upcoming, overdue = _obligations(session, company, report_date)
    gap_amount = forecast.get("gap_amount")
    alerts = []
    for item in evaluated["alerts"]:
        if item["status"] not in {"open", "acknowledged"}:
            continue
        magnitude = _magnitude(item)
        alerts.append(
            {
                "id": item["id"],
                "company_id": str(company.id),
                "company_name": company.name,
                "type": item["type"],
                "severity": item["severity"],
                "materiality": None if magnitude is None else money_str(magnitude),
                "text": _alert_text(item, privacy),
            }
        )
    freshness = _freshness(session, company, report_date)
    return {
        "company_id": str(company.id),
        "name": company.name,
        "cash_total": summary["cash_total"],
        "available": summary["available"],
        "restricted": summary["restricted"],
        "headroom": summary["headroom"],
        "incoming": incoming,
        "outgoing": outgoing,
        "revenue_yesterday": revenue_day["amount"],
        "revenue_mtd": revenue_mtd["amount"],
        "revenue_label": revenue_day["label"],
        "budget": _budget_line(plan),
        "gap_date": forecast.get("gap_date"),
        "gap_amount": gap_amount,
        "upcoming": upcoming,
        "overdue": overdue,
        "freshness": freshness,
        "alerts": alerts,
        "quality_flags": list(summary["quality_flags"]) + list(revenue_day["quality_flags"]),
    }


def _blocks(metrics: dict) -> list[str]:
    formed = metrics["formed_at"]
    header = (
        f"Сводка за {escape_html(metrics['report_date'])}. "
        f"Фирм: {len(metrics['companies'])}. "
        f"Данные по {escape_html(metrics['report_date'])}, сформировано {escape_html(formed)}."
    )
    blocks = [header]
    if metrics["partial"]:
        blocks.append("Групповой итог предварительный: неполный агрегат.")
    gaps = [
        card
        for card in metrics["companies"]
        if card["gap_amount"] not in {None, "0.00"}
    ]
    if gaps:
        lines = [
            f"{escape_html(card['name'])} {escape_html(str(card['gap_date']))}: "
            f"дефицит {escape_html(str(card['gap_amount']))}"
            for card in gaps
        ]
        blocks.append("Внимание: " + "; ".join(lines))
    if metrics["mode"] in {"group", "both"}:
        blocks.append(_money_block(metrics["totals"]))
        blocks.append(_flow_block(metrics["totals"]))
        blocks.append(_revenue_block(metrics["totals"]))
    for card in metrics["companies"]:
        blocks.append(_card_block(card))
    if metrics["alerts"]:
        blocks.append("Проверить: " + "; ".join(item["text"] for item in metrics["alerts"]))
    else:
        blocks.append("Открытых сигналов в сводке нет.")
    freshness = [line for card in metrics["companies"] for line in card["freshness"]]
    if freshness:
        blocks.append("Свежесть: " + "; ".join(freshness))
    return blocks


def _money_block(totals: dict) -> str:
    return (
        "Деньги всего "
        f"{_shown(totals['cash_total'])}, доступны {_shown(totals['available'])}, "
        f"restricted {_shown(totals['restricted'])}."
    )


def _flow_block(totals: dict) -> str:
    return (
        f"Вчера поступления {_shown(totals['incoming'])}, "
        f"списания {_shown(totals['outgoing'])}, "
        f"денежный поток {_shown(totals['net'])}."
    )


def _revenue_block(totals: dict) -> str:
    return (
        f"Выручка вчера: {_shown(totals['revenue_yesterday'])}. "
        f"Выручка MTD: {_shown(totals['revenue_mtd'])}."
    )


def _card_block(card: dict) -> str:
    budget = card["budget"]
    budget_text = "Бюджет: нет данных"
    if budget is not None:
        budget_text = (
            f"Бюджет {escape_html(budget['metric'])}: факт {_shown(budget['fact'])} "
            f"при плане {_shown(budget['plan'])}, {escape_html(budget['status'])}"
        )
    return "\n".join(
        [
            escape_html(card["name"]),
            f"Доступно {_shown(card['available'])}",
            f"Поступления вчера: {_shown(card['incoming'])}",
            f"Выручка вчера: {_shown(card['revenue_yesterday'])}",
            budget_text,
            f"Выплаты 7 дней {_shown(card['upcoming'])}, просрочка {_shown(card['overdue'])}",
        ]
    )


def _shown(value) -> str:
    if value is None:
        return "нет данных"
    return escape_html(str(value))


def _totals(cards: list[dict], partial: bool) -> dict:
    def combine(key: str):
        if not cards or partial or any(card[key] is None for card in cards):
            return None
        total = sum((Decimal(card[key]) for card in cards), Decimal("0"))
        return money_str(total)

    incoming = combine("incoming")
    outgoing = combine("outgoing")
    net = None
    if incoming is not None and outgoing is not None:
        net = money_str(Decimal(incoming) - Decimal(outgoing))
    return {
        "cash_total": combine("cash_total"),
        "available": combine("available"),
        "restricted": combine("restricted"),
        "incoming": incoming,
        "outgoing": outgoing,
        "net": net,
        "revenue_yesterday": combine("revenue_yesterday"),
        "revenue_mtd": combine("revenue_mtd"),
    }


def _budget_line(plan: dict) -> dict | None:
    for basis in plan["bases"]:
        if basis["status"] == "unavailable":
            continue
        for line in basis["lines"]:
            if line["metric_type"] in {"cash_out", "revenue"}:
                return {
                    "metric": line["metric_type"],
                    "plan": line["plan_to_date"],
                    "fact": line["fact"],
                    "status": line["status"],
                }
    return None


def _day_flows(session, company: Company, day: date) -> tuple[str, str]:
    rows = session.scalars(
        select(CashTransaction).where(
            CashTransaction.tenant_id == company.tenant_id,
            CashTransaction.company_id == company.id,
            CashTransaction.business_date == day,
            CashTransaction.status == "posted",
        )
    ).all()
    groups = {
        item.id: item
        for item in session.scalars(
            select(TransferGroup).where(TransferGroup.tenant_id == company.tenant_id)
        ).all()
    }
    incoming = Decimal("0")
    outgoing = Decimal("0")
    for row in rows:
        group = None if row.transfer_group_id is None else groups.get(row.transfer_group_id)
        if group is not None and group.kind == "internal" and group.status == "linked":
            continue
        if row.direction == "in":
            incoming += row.amount
        else:
            outgoing += row.amount
    return money_str(incoming), money_str(outgoing)


def _obligations(session, company: Company, report_date: date) -> tuple[str, str]:
    upcoming = Decimal("0")
    overdue = Decimal("0")
    horizon = report_date + timedelta(days=7)
    for event, residual in slices_for(session, company):
        if residual <= 0 or event.direction != "out":
            continue
        if event.due_date < report_date:
            overdue += residual
        elif event.due_date <= horizon:
            upcoming += residual
    return money_str(upcoming), money_str(overdue)


def _freshness(session, company: Company, report_date: date) -> list[str]:
    sources = session.scalars(
        select(SourceConnection).where(
            SourceConnection.tenant_id == company.tenant_id,
            SourceConnection.company_id == company.id,
            SourceConnection.enabled.is_(True),
        )
    ).all()
    lines = []
    for source in sources:
        if source.coverage_through is None:
            lines.append(f"{escape_html(source.name)}: покрытие нет данных")
        elif source.coverage_through < report_date:
            lines.append(
                f"{escape_html(source.name)}: покрытие только {source.coverage_through.isoformat()}"
            )
    return lines


def _alert_text(item: dict, privacy: str) -> str:
    evidence = item.get("evidence") or {}
    magnitude = _magnitude(item)
    amount = "" if magnitude is None else money_str(magnitude)
    text = f"{escape_html(item['type'])} {escape_html(amount)}".strip()
    if privacy == "full":
        for key, value in evidence.items():
            if key in HIDDEN and value:
                text += f" {escape_html(str(value))}"
    return text


def _magnitude(item: dict) -> Decimal | None:
    key = MAGNITUDE.get(item["type"])
    if key is None:
        return None
    raw = (item.get("evidence") or {}).get(key)
    if raw is None or raw == "":
        stored = item.get("materiality")
        raw = stored
    if raw is None or raw == "":
        return None
    try:
        return money(abs(Decimal(str(raw))))
    except Exception:
        return None


def _previous_materiality(
    session, tenant_id, alert_id: str
) -> tuple[Decimal | None, datetime | None]:
    rows = session.scalars(
        select(NotificationOutbox).where(
            NotificationOutbox.tenant_id == tenant_id,
            NotificationOutbox.status == "sent",
        )
    ).all()
    found: tuple[Decimal | None, datetime | None] = (None, None)
    for row in rows:
        payload = row.payload or {}
        matched = payload.get("alert_id") == alert_id
        if not matched:
            matched = any(item.get("id") == alert_id for item in payload.get("alerts") or [])
        if not matched or row.sent_at is None:
            continue
        raw = payload.get("materiality")
        if raw is None:
            for item in payload.get("alerts") or []:
                if item.get("id") == alert_id:
                    raw = item.get("materiality")
        if raw is None:
            continue
        if found[1] is None or row.sent_at > found[1]:
            found = (Decimal(str(raw)), row.sent_at)
    return found


def _cooldown(session, item: dict) -> int:
    rule = session.scalar(
        select(AlertRule).where(
            AlertRule.company_id == uuid.UUID(item["company_id"]),
            AlertRule.rule_type == item["type"],
        )
    )
    if rule is None:
        return 360
    return rule.cooldown_minutes


def _can_read(session, membership, company, user, settings, at) -> bool:
    try:
        assert_finance_access(
            session,
            membership=membership,
            company=company,
            user_verified=user.email_verified_at is not None,
            at=at,
            mode="read",
            grace_days=settings.billing_grace_days,
            bypass=settings.billing_bypass_allowed(),
        )
    except AppError:
        return False
    return True


def _require_subscription(session, membership, user) -> DigestSubscription:
    binding = session.scalar(
        select(TelegramBinding).where(
            TelegramBinding.tenant_id == membership.tenant_id,
            TelegramBinding.user_id == user.id,
            TelegramBinding.status == "active",
        )
    )
    if binding is None:
        raise AppError(409, "binding_required", "Сначала подтвердите привязку")
    row = session.scalar(
        select(DigestSubscription).where(
            DigestSubscription.tenant_id == membership.tenant_id,
            DigestSubscription.binding_id == binding.id,
        )
    )
    if row is None or not row.enabled:
        raise AppError(404, "not_found", "Подписка выключена")
    return row


def _membership(session, subscription: DigestSubscription) -> Membership | None:
    from app.models.identity import Membership as MembershipRow

    return session.scalar(
        select(MembershipRow).where(
            MembershipRow.tenant_id == subscription.tenant_id,
            MembershipRow.user_id == subscription.user_id,
            MembershipRow.status == "active",
        )
    )


def _report_date(subscription: DigestSubscription, at: datetime) -> date:
    zone = zone_of(subscription.timezone)
    return at.astimezone(zone).date() - timedelta(days=1)
