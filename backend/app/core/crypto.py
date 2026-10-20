"""Encryption at rest for third-party secrets (Telegram Ads tokens, bot API keys, Claude key).

The key comes from ENCRYPTION_KEY in the environment and never touches the database.
Several comma-separated keys are accepted for rotation: the first encrypts, all decrypt.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings


class SecretError(Exception):
    pass


@lru_cache
def _fernet() -> MultiFernet:
    raw = get_settings().encryption_key.get_secret_value()
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise SecretError("ENCRYPTION_KEY is not set")
    try:
        return MultiFernet([Fernet(k.encode()) for k in keys])
    except (ValueError, TypeError) as e:
        raise SecretError("ENCRYPTION_KEY is not a valid Fernet key") from e


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(token: str | None) -> str:
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise SecretError("stored secret cannot be decrypted with the current ENCRYPTION_KEY") from e


def last4(plain: str) -> str:
    plain = plain.strip()
    return plain[-4:] if len(plain) >= 8 else ""


def generate_key() -> str:
    return Fernet.generate_key().decode("ascii")
