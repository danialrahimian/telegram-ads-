"""Global settings stored in the database (Claude key, UI refresh, admin password hash)."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import fingerprint, hash_password, verify_password
from app.integrations.anthropic import DEFAULT_MODEL
from app.models import AppSetting

DEFAULTS: dict[str, Any] = {
    "claude_model": DEFAULT_MODEL,
    "ui_refresh_seconds": 5,
}


async def get(s: AsyncSession, key: str, default: Any = None) -> Any:
    row = await s.get(AppSetting, key)
    if row is None:
        return DEFAULTS.get(key, default)
    return row.value


async def put(s: AsyncSession, key: str, value: Any) -> None:
    row = await s.get(AppSetting, key)
    if row is None:
        s.add(AppSetting(key=key, value=value))
    else:
        row.value = value


async def public(s: AsyncSession) -> dict[str, Any]:
    enc = await get(s, "claude_api_key_enc", "")
    return {
        "claude_model": await get(s, "claude_model"),
        "claude_key_set": bool(enc),
        "claude_key_last4": await get(s, "claude_key_last4", ""),
        "ui_refresh_seconds": await get(s, "ui_refresh_seconds"),
    }


async def claude_key(s: AsyncSession) -> str:
    return crypto.decrypt(await get(s, "claude_api_key_enc", ""))


async def set_claude_key(s: AsyncSession, key: str | None) -> None:
    if key is None:
        return
    key = key.strip()
    if not key:
        await put(s, "claude_api_key_enc", "")
        await put(s, "claude_key_last4", "")
        return
    await put(s, "claude_api_key_enc", crypto.encrypt(key))
    await put(s, "claude_key_last4", crypto.last4(key))


# ---- admin password ----


async def sync_env_password(s: AsyncSession) -> None:
    """ADMIN_PASSWORD in .env is the bootstrap password. If it changes (tgads password), it wins."""
    env_pw = get_settings().admin_password.get_secret_value()
    if not env_pw:
        return
    fp = fingerprint(env_pw)
    if await get(s, "admin_env_fingerprint") != fp:
        await put(s, "admin_password_hash", hash_password(env_pw))
        await put(s, "admin_env_fingerprint", fp)


async def check_password(s: AsyncSession, password: str) -> bool:
    stored = await get(s, "admin_password_hash")
    if not stored:
        return False
    return verify_password(password, stored)


async def change_password(s: AsyncSession, current: str, new: str) -> None:
    if not await check_password(s, current):
        raise AppError("رمز فعلی اشتباه است.", code="wrong_password")
    if len(new) < 8:
        raise AppError("رمز جدید باید دست‌کم ۸ کاراکتر باشد.")
    await put(s, "admin_password_hash", hash_password(new))
