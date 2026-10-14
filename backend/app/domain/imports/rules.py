from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class RuleView:
    priority: int
    enabled: bool
    conditions: dict
    category_code: str


def matching_category(
    rules: tuple[RuleView, ...],
    *,
    description: str,
    counterparty_inn: str,
    direction: str,
    amount: Decimal | None,
) -> str | None:
    ordered = sorted((item for item in rules if item.enabled), key=lambda item: item.priority)
    for rule in ordered:
        if _matches(rule.conditions, description, counterparty_inn, direction, amount):
            return rule.category_code or None
    return None


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
