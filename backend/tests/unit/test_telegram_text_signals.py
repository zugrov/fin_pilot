from app.domain.telegram_text import (
    UNKNOWN_SIGNAL_LABEL,
    signal_type_label,
)


def test_known_signal_has_russian_label() -> None:
    assert signal_type_label("cash_gap") == "Дефицит денег"
    assert "cash_gap" not in signal_type_label("cash_gap")


def test_unknown_signal_uses_safe_fallback() -> None:
    label = signal_type_label("future_rule_xyz")
    assert label == UNKNOWN_SIGNAL_LABEL
    assert "future_rule_xyz" not in label
