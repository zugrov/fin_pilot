from app.domain.imports.fa_r03.deposit_heuristics import (
    deposit_operation_bucket,
    is_deposit_like_cash_description,
)


def test_deposit_placement_detected() -> None:
    assert deposit_operation_bucket("РАЗМЕЩЕНИЕ ДЕПОЗИТА на счёт") == "placement"
    assert is_deposit_like_cash_description("размещение вклада")


def test_non_deposit_returns_none() -> None:
    assert deposit_operation_bucket("Оплата по счёту") is None
    assert not is_deposit_like_cash_description("Оплата")
