from decimal import Decimal
from uuid import UUID

from app.domain.imports.rules import RuleView, matching_rule, rule_conflict_at_tx


def _view(rule_id: str, priority: int, category: str, *, needle: str = "Оплата") -> RuleView:
    return RuleView(
        rule_id=UUID(rule_id),
        rule_version=1,
        priority=priority,
        enabled=True,
        conditions={"description_contains": needle, "direction": "in"},
        category_code=category,
    )


def test_matching_tie_break_by_rule_id() -> None:
    low = _view("00000000-0000-4000-8000-000000000001", 10, "operating")
    high = _view("00000000-0000-4000-8000-000000000002", 10, "investing")
    shuffled = (high, low)
    first = matching_rule(
        shuffled,
        description="Оплата retail",
        counterparty_inn="",
        direction="in",
        amount=Decimal("100.00"),
    )
    second = matching_rule(
        (low, high),
        description="Оплата retail",
        counterparty_inn="",
        direction="in",
        amount=Decimal("100.00"),
    )
    assert first is not None and second is not None
    assert first.rule_id == low.rule_id
    assert second.rule_id == low.rule_id


def test_rule_conflict_at_equal_priority() -> None:
    rules = (
        _view("00000000-0000-4000-8000-00000000000a", 5, "operating"),
        _view("00000000-0000-4000-8000-00000000000b", 5, "investing"),
    )
    conflict = rule_conflict_at_tx(
        rules,
        description="Оплата retail",
        counterparty_inn="",
        direction="in",
        amount=Decimal("1.00"),
    )
    assert conflict is not None
    assert conflict.priority == 5
    assert len(conflict.category_codes) == 2
