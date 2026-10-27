"""Установка каталоговых наборов ClassificationRule (без расширения модели условий)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from app.catalog.classification_packs.loader import ClassificationPack, load_pack, rule_priority
from app.config import Settings
from app.domain.imports.rules import RuleView, matching_category, matching_rule
from app.domain.money import money_str
from app.errors import AppError
from app.models.cash import CashCategory, CashTransaction
from app.models.identity import AuditLog, Company, Membership, User
from app.models.imports import ClassificationRule
from app.services.import_service import apply_classification_rule, create_rule, load_rule_views
from sqlalchemy import select
from sqlalchemy.orm import Session

PACK_INSTALL_ACTION = "classification_rule_installed_from_pack"
SECTIONS = ("operating", "investing", "financing", "technical", "unmapped")


def require_classification_packs_enabled(settings: Settings) -> None:
    if not settings.classification_packs_enabled:
        raise AppError(404, "not_found", "Маршрут недоступен")


def _pack_install_audit(
    session: Session,
    user: User,
    tenant_id: uuid.UUID,
    rule_id: uuid.UUID,
    *,
    pack: str,
    version: str,
    rule_key: str,
    at: datetime,
) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user.id,
            action=PACK_INSTALL_ACTION,
            entity_type="classification_rule",
            entity_id=rule_id,
            before_redacted=None,
            after_redacted={
                "pack": pack,
                "version": version,
                "rule_key": rule_key,
                "rule_id": str(rule_id),
            },
            request_id=None,
            created_at=at,
        )
    )


def _installed_audits(
    session: Session, company: Company, pack_slug: str, version: str | None = None
) -> list[AuditLog]:
    rows = session.scalars(
        select(AuditLog).where(
            AuditLog.tenant_id == company.tenant_id,
            AuditLog.action == PACK_INSTALL_ACTION,
        )
    ).all()
    matched: list[AuditLog] = []
    for row in rows:
        payload = row.after_redacted or {}
        if payload.get("pack") != pack_slug:
            continue
        if version is not None and payload.get("version") != version:
            continue
        matched.append(row)
    return matched


def _find_prior_install(
    session: Session, company: Company, pack_slug: str, rule_key: str
) -> AuditLog | None:
    for row in _installed_audits(session, company, pack_slug, version=None):
        payload = row.after_redacted or {}
        if payload.get("rule_key") == rule_key:
            return row
    return None


def _pack_rule_views(pack: ClassificationPack) -> tuple[RuleView, ...]:
    views: list[RuleView] = []
    for spec in pack.rules:
        views.append(
            RuleView(
                rule_id=uuid.uuid5(uuid.NAMESPACE_OID, f"{pack.slug}:{pack.version}:{spec.key}"),
                rule_version=1,
                priority=rule_priority(pack, spec),
                enabled=True,
                conditions=dict(spec.conditions),
                category_code=spec.category_code,
            )
        )
    return tuple(views)


def _section_for_category(session: Session, company: Company, code: str) -> str:
    category = session.scalar(
        select(CashCategory).where(
            CashCategory.tenant_id == company.tenant_id,
            CashCategory.code == code,
        )
    )
    if category is None or category.cash_flow_section not in SECTIONS:
        return "unmapped"
    return category.cash_flow_section


def _posted_in_period(
    session: Session, company: Company, date_from: date, date_to: date
) -> list[CashTransaction]:
    return list(
        session.scalars(
            select(CashTransaction).where(
                CashTransaction.tenant_id == company.tenant_id,
                CashTransaction.company_id == company.id,
                CashTransaction.status == "posted",
                CashTransaction.business_date >= date_from,
                CashTransaction.business_date <= date_to,
            )
        ).all()
    )


def preview_pack(
    session: Session,
    company: Company,
    pack_slug: str,
    version: str,
    *,
    date_from: date,
    date_to: date,
) -> dict:
    pack = load_pack(pack_slug, version)
    existing = load_rule_views(session, company)
    pack_views = _pack_rule_views(pack)
    combined = existing + pack_views

    incoming = {code: Decimal("0") for code in SECTIONS}
    outgoing = {code: Decimal("0") for code in SECTIONS}
    unmapped_count = 0
    intersections: list[dict] = []
    intersection_keys: set[tuple[str, str]] = set()

    txs = _posted_in_period(session, company, date_from, date_to)
    for tx in txs:
        desc = tx.description or ""
        inn = tx.counterparty_inn or ""
        winner = matching_category(
            combined,
            description=desc,
            counterparty_inn=inn,
            direction=tx.direction,
            amount=tx.amount,
        )
        existing_only = matching_category(
            existing,
            description=desc,
            counterparty_inn=inn,
            direction=tx.direction,
            amount=tx.amount,
        )
        pack_only = matching_category(
            pack_views,
            description=desc,
            counterparty_inn=inn,
            direction=tx.direction,
            amount=tx.amount,
        )
        if existing_only and pack_only and existing_only != pack_only and winner == existing_only:
            ex_rule = matching_rule(
                existing,
                description=desc,
                counterparty_inn=inn,
                direction=tx.direction,
                amount=tx.amount,
            )
            pk_rule = matching_rule(
                pack_views,
                description=desc,
                counterparty_inn=inn,
                direction=tx.direction,
                amount=tx.amount,
            )
            if ex_rule and pk_rule:
                key = (str(ex_rule.rule_id), str(pk_rule.rule_id))
                if key not in intersection_keys:
                    intersection_keys.add(key)
                    intersections.append(
                        {
                            "existing_rule_id": str(ex_rule.rule_id),
                            "pack_rule_key": _pack_key_for_view(pack, pk_rule.rule_id),
                            "winner": "existing",
                            "existing_priority": _priority(existing, ex_rule.rule_id),
                            "pack_priority": _priority(pack_views, pk_rule.rule_id),
                        }
                    )
        if winner is None:
            unmapped_count += 1
            section = "unmapped"
        else:
            section = _section_for_category(session, company, winner)
        if tx.direction == "in":
            incoming[section] += tx.amount
        else:
            outgoing[section] += tx.amount

    return {
        "pack": pack_slug,
        "version": version,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "transaction_count": len(txs),
        "unmapped_count": unmapped_count,
        "sections": [
            {
                "code": code,
                "in": money_str(incoming[code]),
                "out": money_str(outgoing[code]),
            }
            for code in SECTIONS
        ],
        "intersections_with_existing": intersections,
        "pack_rule_count": len(pack.rules),
    }


def _pack_key_for_view(pack: ClassificationPack, rule_id: uuid.UUID) -> str:
    for spec, view in zip(pack.rules, _pack_rule_views(pack), strict=True):
        if view.rule_id == rule_id:
            return spec.key
    return ""


def _priority(rules: tuple[RuleView, ...], rule_id: uuid.UUID) -> int:
    for item in rules:
        if item.rule_id == rule_id:
            return item.priority
    return 0


def install_pack(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    pack_slug: str,
    version: str,
    *,
    idempotency_key: str,
    at: datetime,
) -> dict:
    pack = load_pack(pack_slug, version)
    created: list[dict] = []
    skipped: list[dict] = []
    version_conflicts: list[dict] = []

    for spec in pack.rules:
        prior = _find_prior_install(session, company, pack_slug, spec.key)
        if prior is not None:
            payload = prior.after_redacted or {}
            if payload.get("version") != version:
                version_conflicts.append(
                    {
                        "rule_key": spec.key,
                        "installed_version": payload.get("version"),
                        "requested_version": version,
                        "rule_id": payload.get("rule_id"),
                    }
                )
                continue
            skipped.append(
                {
                    "rule_key": spec.key,
                    "rule_id": payload.get("rule_id"),
                    "reason": "already_installed",
                }
            )
            continue

        rule_key_header = f"{idempotency_key}:{spec.key}"
        body = create_rule(
            session,
            membership,
            company,
            user,
            settings,
            name=pack.rule_name(spec),
            priority=rule_priority(pack, spec),
            conditions=dict(spec.conditions),
            category_code=spec.category_code,
            idempotency_key=rule_key_header,
            at=at,
        )
        rule_id = uuid.UUID(body["id"])
        _pack_install_audit(
            session,
            user,
            company.tenant_id,
            rule_id,
            pack=pack_slug,
            version=version,
            rule_key=spec.key,
            at=at,
        )
        created.append({"rule_key": spec.key, "rule_id": str(rule_id)})

    return {
        "pack": pack_slug,
        "version": version,
        "created": created,
        "skipped": skipped,
        "version_conflicts": version_conflicts,
    }


def disable_pack(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    pack_slug: str,
    version: str,
    at: datetime,
) -> dict:
    from app.services.import_service import update_classification_rule

    audits = _installed_audits(session, company, pack_slug, version)
    if not audits:
        raise AppError(404, "not_found", "Набор не установлен")
    disabled: list[str] = []
    for row in audits:
        rule_id = row.entity_id
        if rule_id is None:
            continue
        update_classification_rule(
            session,
            membership,
            company,
            user,
            settings,
            rule_id,
            enabled=False,
            priority=None,
            name=None,
            at=at,
        )
        disabled.append(str(rule_id))
    return {"pack": pack_slug, "version": version, "disabled_rule_ids": disabled}


def apply_pack(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    pack_slug: str,
    version: str,
    at: datetime,
) -> dict:
    audits = _installed_audits(session, company, pack_slug, version)
    if not audits:
        raise AppError(404, "not_found", "Набор не установлен")
    rule_ids = [row.entity_id for row in audits]
    rules = session.scalars(
        select(ClassificationRule).where(ClassificationRule.id.in_(rule_ids))
    ).all()
    rules_sorted = sorted(rules, key=lambda item: (item.priority, str(item.id)))
    totals = {
        "applied": 0,
        "skipped_locked": 0,
        "skipped_categorized": 0,
        "skipped_higher_priority": 0,
        "total_matches": 0,
    }
    for rule in rules_sorted:
        if not rule.enabled:
            continue
        after_date = None
        after_id = None
        while True:
            chunk = apply_classification_rule(
                session,
                membership,
                user,
                settings,
                company,
                rule.id,
                at=at,
                after_business_date=after_date,
                after_transaction_id=after_id,
            )
            for key in totals:
                if key in chunk:
                    totals[key] += chunk[key]
            if not chunk.get("has_more"):
                break
            cursor = chunk["cursor"]
            after_date = date.fromisoformat(cursor["business_date"])
            after_id = uuid.UUID(cursor["transaction_id"])
    return {"pack": pack_slug, "version": version, **totals}
