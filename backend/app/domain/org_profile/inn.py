"""Проверка ИНН (формат и контрольная сумма), без внешних запросов."""


def validate_inn_checksum(inn: str | None) -> list[str]:
    """Возвращает коды ошибок (пусто — валидно или ИНН не задан)."""
    if inn is None or inn == "":
        return []
    if not inn.isdigit():
        return ["inn_not_digits"]
    length = len(inn)
    if length == 10:
        return _validate_legal_entity(inn)
    if length == 12:
        return _validate_individual(inn)
    return ["inn_invalid_length"]


def _validate_legal_entity(inn: str) -> list[str]:
    coeffs = (2, 4, 10, 3, 5, 9, 4, 6, 8)
    checksum = _checksum_digit(inn[:9], coeffs)
    if checksum != int(inn[9]):
        return ["inn_checksum_mismatch"]
    return []


def _validate_individual(inn: str) -> list[str]:
    coeffs_1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
    coeffs_2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
    check_1 = _checksum_digit(inn[:10], coeffs_1)
    check_2 = _checksum_digit(inn[:11], coeffs_2)
    if check_1 != int(inn[10]) or check_2 != int(inn[11]):
        return ["inn_checksum_mismatch"]
    return []


def _checksum_digit(digits: str, coeffs: tuple[int, ...]) -> int:
    total = sum(int(d) * c for d, c in zip(digits, coeffs, strict=True))
    return total % 11 % 10
