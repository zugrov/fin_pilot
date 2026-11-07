import pytest
from app.domain.org_profile.inn import validate_inn_checksum


@pytest.mark.parametrize(
    "inn",
    [
        "7707083893",
        "500100732259",
    ],
)
def test_inn_valid_samples(inn: str) -> None:
    assert validate_inn_checksum(inn) == []


def test_inn_empty_ok() -> None:
    assert validate_inn_checksum(None) == []
    assert validate_inn_checksum("") == []


def test_inn_bad_checksum() -> None:
    assert "inn_checksum_mismatch" in validate_inn_checksum("7707083890")


def test_inn_invalid_length() -> None:
    assert validate_inn_checksum("123") == ["inn_invalid_length"]
