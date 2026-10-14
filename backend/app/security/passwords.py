from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

_hasher = PasswordHasher()
_dummy_hash = _hasher.hash("dummy-password-not-used")

MIN_PASSWORD_LENGTH = 12


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    candidate = password_hash or _dummy_hash
    try:
        return _hasher.verify(candidate, password) and password_hash is not None
    except VerifyMismatchError:
        return False
