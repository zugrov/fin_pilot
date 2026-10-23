from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RuleView:
    rule_id: uuid.UUID
    rule_version: int
    priority: int
    enabled: bool
    conditions: dict
    category_code: str


@dataclass(frozen=True)
class MatchResult:
    rule_id: uuid.UUID
    rule_version: int
    category_code: str


@dataclass(frozen=True)
class RuleConflictAtPriority:
    priority: int
    rule_ids: tuple[str, ...]
    category_codes: tuple[str, ...]


def _sort_key(item: RuleView) -> tuple[int, str]:
    return item.priority, str(item.rule_id)


def _ordered_enabled(rules: tuple[RuleView, ...]) -> tuple[RuleView, ...]:
    return tuple(sorted((item for item in rules if item.enabled), key=_sort_key))


def matching_rule(
    rules: tuple[RuleView, ...],
    *,
    description: str,
    counterparty_inn: str,
    direction: str,
    amount: Decimal | None,
) -> MatchResult | None:
    for rule in _ordered_enabled(rules):
        if _matches(rule.conditions, description, counterparty_inn, direction, amount):
            return MatchResult(rule.rule_id, rule.rule_version, rule.category_code or "")
    return None


def matching_category(
    rules: tuple[RuleView, ...],
    *,
    description: str,
    counterparty_inn: str,
    direction: str,
    amount: Decimal | None,
) -> str | None:
    matched = matching_rule(
        rules,
        description=description,
        counterparty_inn=counterparty_inn,
        direction=direction,
        amount=amount,
    )
    if matched is None or not matched.category_code:
        return None
    return matched.category_code


def rule_conflict_at_tx(
    rules: tuple[RuleView, ...],
    *,
    description: str,
    counterparty_inn: str,
    direction: str,
    amount: Decimal | None,
) -> RuleConflictAtPriority | None:
    matches = [
        rule
        for rule in _ordered_enabled(rules)
        if _matches(rule.conditions, description, counterparty_inn, direction, amount)
    ]
    if len(matches) < 2:
        return None
    min_priority = matches[0].priority
    at_min = [item for item in matches if item.priority == min_priority]
    codes = {item.category_code for item in at_min if item.category_code}
    if len(codes) <= 1:
        return None
    return RuleConflictAtPriority(
        priority=min_priority,
        rule_ids=tuple(str(item.rule_id) for item in at_min),
        category_codes=tuple(sorted(codes)),
    )


def aggregate_rule_conflicts(
    rules: tuple[RuleView, ...],
    transactions: tuple[dict, ...],
) -> list[dict]:
    """transactions: dicts with description, counterparty_inn, direction, amount."""
    by_priority: dict[int, dict] = {}
    for tx in transactions:
        conflict = rule_conflict_at_tx(
            rules,
            description=str(tx.get("description") or ""),
            counterparty_inn=str(tx.get("counterparty_inn") or ""),
            direction=str(tx["direction"]),
            amount=tx.get("amount"),
        )
        if conflict is None:
            continue
        bucket = by_priority.setdefault(
            conflict.priority,
            {
                "code": "classification_rule_conflict",
                "message": (
                    f"Несколько правил с приоритетом {conflict.priority} дают разные категории; "
                    "применено правило с наименьшим id."
                ),
                "priority": conflict.priority,
                "rule_ids": set(conflict.rule_ids),
                "affected_transactions": 0,
            },
        )
        bucket["rule_ids"].update(conflict.rule_ids)
        bucket["affected_transactions"] += 1
    warnings: list[dict] = []
    for item in sorted(by_priority.values(), key=lambda row: row["priority"]):
        warnings.append(
            {
                "code": item["code"],
                "message": item["message"],
                "priority": item["priority"],
                "rule_ids": sorted(item["rule_ids"]),
                "affected_transactions": item["affected_transactions"],
            }
        )
    return warnings


def create_rule_conflict_warning(
    *,
    priority: int,
    new_rule_id: uuid.UUID,
    new_category_code: str,
    siblings: tuple[RuleView, ...],
) -> dict | None:
    conflicting = [
        item
        for item in siblings
        if item.enabled
        and item.priority == priority
        and item.rule_id != new_rule_id
        and item.category_code
        and item.category_code != new_category_code
    ]
    if not conflicting:
        return None
    rule_ids = sorted({str(new_rule_id), *(str(item.rule_id) for item in conflicting)})
    return {
        "code": "classification_rule_conflict",
        "message": (
            f"Несколько правил с приоритетом {priority} задают разные категории; "
            "при конфликте побеждает правило с наименьшим id."
        ),
        "priority": priority,
        "rule_ids": rule_ids,
    }


def _matches(
    conditions: dict,
    description: str,
    counterparty_inn: str,
    direction: str,
    amount: Decimal | None,
) -> bool:
    needle = str(conditions.get("description_contains") or "")
    if needle and needle.casefold() not in description.casefold():
        return False
    expected_inn = str(conditions.get("counterparty_inn") or "")
    if expected_inn and expected_inn != counterparty_inn:
        return False
    expected_direction = str(conditions.get("direction") or "")
    if expected_direction and expected_direction != direction:
        return False
    if amount is None and ("amount_min" in conditions or "amount_max" in conditions):
        return False
    if "amount_min" in conditions and amount is not None:
        if amount < Decimal(str(conditions["amount_min"])):
            return False
    if "amount_max" in conditions and amount is not None:
        if amount > Decimal(str(conditions["amount_max"])):
            return False
    return True
