"""Эвристики депозитных операций (общие для CLI и FA-R03.4)."""

DEPOSIT_PLACEMENT = ("РАЗМЕЩЕНИЕ ВКЛАД", "РАЗМЕЩЕНИЕ ДЕПОЗ", "ВО ВКЛАД", "НА ДЕПОЗ")
DEPOSIT_RETURN = ("ВОЗВРАТ ДЕПОЗИТ", "ВОЗВРАТ ВКЛАД")
DEPOSIT_INTEREST = ("ПРОЦЕНТОВ ПО ДЕПОЗ",)


def deposit_operation_bucket(description: str) -> str | None:
    upper = (description or "").upper()
    if any(marker in upper for marker in DEPOSIT_PLACEMENT):
        return "placement"
    if any(marker in upper for marker in DEPOSIT_RETURN):
        return "return"
    if any(marker in upper for marker in DEPOSIT_INTEREST):
        return "interest"
    return None


def is_deposit_like_cash_description(description: str) -> bool:
    return deposit_operation_bucket(description) is not None
