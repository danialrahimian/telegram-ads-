from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.integrations.bot_api import extract_rows, norm_transaction, norm_user, normalize_base_url, to_ts
from app.integrations.telegram_ads import TelegramAdsError, floor_amount


def test_extract_rows_accepts_common_shapes():
    rows = [{"id": 1}, {"id": 2}]
    assert extract_rows(rows) == rows
    assert extract_rows({"transactions": rows, "total": 2}) == rows
    assert extract_rows({"data": {"items": rows}}) == rows
    assert extract_rows({"whatever": rows}) == rows
    assert extract_rows({"count": 3}) == []
    assert extract_rows(None) == []


def test_to_ts_formats():
    tehran = ZoneInfo("Asia/Tehran")
    assert to_ts(1700000000) == 1700000000
    assert to_ts(1700000000123) == 1700000000
    assert to_ts("1700000000") == 1700000000
    utc = int(datetime(2026, 10, 2, 14, 21, tzinfo=UTC).timestamp())
    assert to_ts("2026-10-02 14:21:00") == utc
    assert to_ts("2026/10/02 14:21:00") == utc
    assert to_ts("2026-10-02 14:21:00", tehran) == utc - 3 * 3600 - 1800
    assert to_ts("2026-10-02") == int(datetime(2026, 10, 2, tzinfo=UTC).timestamp())
    assert to_ts("not a date") == 0
    assert to_ts(None) == 0


def test_normalizers():
    t = norm_transaction({"id": 5, "id_user": "123", "type": "buy", "amount": "59,000", "created_at": "2026-10-02"})
    assert t["ext_id"] == "5" and t["user_id"] == 123 and t["amount"] == 59000 and t["type"] == "buy"
    t2 = norm_transaction({"user_id": 9, "price": 10})
    t3 = norm_transaction({"user_id": 9, "price": 10})
    assert t2["ext_id"].startswith("h") and t2["ext_id"] == t3["ext_id"]  # stable hash when no id column
    u = norm_user({"chat_id": "777", "register": 1700000000})
    assert u == {"user_id": 777, "registered_ts": 1700000000}


def test_normalize_base_url():
    assert normalize_base_url("https://bot.example.com/api/docs") == "https://bot.example.com"
    assert normalize_base_url("bot.example.com/") == "https://bot.example.com"
    assert normalize_base_url("http://1.2.3.4:8080/panel/api") == "http://1.2.3.4:8080/panel"
    with pytest.raises(ValueError):
        normalize_base_url("ftp://x")


def test_floor_amount_never_rounds_up():
    assert floor_amount(1.234567) == 1.23456
    assert floor_amount(0.1 + 0.2) == 0.3


def test_friendly_errors():
    assert "توکن" in TelegramAdsError("getCurrentAccount", "ACCESS_TOKEN_INVALID").friendly
    assert "IP" in TelegramAdsError("getCurrentAccount", "IP_ADDRESS_NOT_ALLOWED").friendly


def test_crypto_and_passwords(env):
    from app.core import crypto
    from app.core.security import LoginLimiter, hash_password, verify_password

    enc = crypto.encrypt("secret-token-123")
    assert enc != "secret-token-123" and crypto.decrypt(enc) == "secret-token-123"
    assert crypto.last4("secret-token-123") == "-123"
    h = hash_password("hunter2hunter2")
    assert verify_password("hunter2hunter2", h) and not verify_password("nope", h)
    lim = LoginLimiter(max_failures=2, window=60)
    lim.fail("ip")
    assert not lim.blocked("ip")
    lim.fail("ip")
    assert lim.blocked("ip")


def test_new_credentials_reset_the_backoff():
    from app.models import Account
    from app.workers.scheduler import Scheduler

    acc = Account(slug="x", name="x", tg_token_enc="enc", settings={}, sync_state={})
    acc.sync_state = {"fast": {"last_try": 1000, "fails": 5, "error": "ACCESS_TOKEN_INVALID", "last_ok": 10}}
    assert Scheduler.due(acc, "fast", 1000 + 60) is False  # backing off after 5 failures
    from app.services.accounts import reset_sync

    reset_sync(acc, ("fast", "stats"))
    assert acc.sync_state["fast"]["fails"] == 0 and acc.sync_state["fast"]["last_ok"] == 10
    assert Scheduler.due(acc, "fast", 1000 + 60) is True


async def test_forced_trigger_reruns_after_the_running_sync(monkeypatch):
    import asyncio

    from app.services import sync
    from app.workers.scheduler import Scheduler

    calls: list[str] = []
    gate = asyncio.Event()

    async def fake_run(account_id: int, kind: str) -> None:
        calls.append(kind)
        if len(calls) == 1:
            await gate.wait()

    monkeypatch.setattr(sync, "run", fake_run)
    sch = Scheduler()
    sch._loop_task = asyncio.get_running_loop().create_future()  # pretend started without the loop
    assert sch.trigger(1, "fast") is True
    await asyncio.sleep(0)
    assert sch.trigger(1, "fast") is False  # already running, not forced: nothing queued
    assert sch.trigger(1, "fast", force=True) is False  # queued for right after
    gate.set()
    for _ in range(20):
        await asyncio.sleep(0)
    assert calls == ["fast", "fast"]
    sch._loop_task.cancel()


def test_user_growth_ignores_counter_resets():
    from app.services.metrics import user_growth

    assert user_growth([100, 101, 105, 105, 110]) == 10
    # a different bot was connected: 101202 -> 50, then normal growth
    assert user_growth([101150, 101202, 50, 101, 159]) == 52 + 51 + 58
    # and the other way round: a jump from a small to a big counter is not growth
    assert user_growth([50, 101202, 101210]) == 8
    assert user_growth([7]) == 0
