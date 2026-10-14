import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings
from app.errors import AppError


def seal_mailbox(settings: Settings, raw: dict) -> tuple[dict, str]:
    host = str(raw.get("host") or "").strip()
    folder = str(raw.get("folder") or "").strip()
    sender = str(raw.get("sender") or "").strip()
    username = str(raw.get("username") or "").strip()
    password = str(raw.get("password") or "")
    if not host or not folder or not sender or not username or not password:
        raise AppError(422, "validation_error", "Нужны сервер, ящик, папка, отправитель и пароль")
    config = {"host": host, "folder": folder, "sender": sender, "username": username}
    return config, encrypt_secret(settings, password)


def encrypt_secret(settings: Settings, raw: str) -> str:
    token = _fernet(settings).encrypt(raw.encode("utf-8"))
    return token.decode("ascii")


def decrypt_secret(settings: Settings, token: str) -> str:
    try:
        raw = _fernet(settings).decrypt(token.encode("ascii"))
    except (InvalidToken, ValueError) as exc:
        raise AppError(422, "validation_error", "Пароль ящика не читается") from exc
    return raw.decode("utf-8")


def _fernet(settings: Settings) -> Fernet:
    digest = hashlib.sha256(settings.secret_encryption_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))
