"""API tests against the real app (lifespan, migrations, SQLite) with Telegram/bot/Claude mocked by respx."""

import io
import json
import zipfile

from sqlalchemy import select

from app.db.session import session_scope
from app.models import Ad, Job, Proposal
from app.services import actions, sync
from tests.conftest import BOT_BASE, PASSWORD, make_account


async def _id(slug: str) -> int:
    from app.models import Account

    async with session_scope() as s:
        return (await s.execute(select(Account.id).where(Account.slug == slug))).scalar_one()


async def _sync_all(slug: str) -> None:
    aid = await _id(slug)
    await sync.run(aid, "fast")
    await sync.run(aid, "stats")
    await sync.run(aid, "bot")


# ---------------------------------------------------------------- auth


async def test_auth_flow(anon):
    r = await anon.get("/api/v1/auth/me")
    assert r.status_code == 200 and r.json()["authenticated"] is False and r.json()["problems"] == []
    assert (await anon.get("/api/v1/accounts")).status_code == 401
    r = await anon.c.post("/api/v1/auth/login", json={"password": "wrong"})
    assert r.status_code == 401 and r.json()["code"] == "wrong_password"
    assert (await anon.login()).status_code == 200
    assert (await anon.get("/api/v1/accounts")).status_code == 200
    # state-changing request without the CSRF header is refused
    r = await anon.c.post("/api/v1/accounts", json={"name": "x", "slug": "xyz"})
    assert r.status_code == 403 and r.json()["code"] == "csrf_failed"
    # change password, then the new one works
    r = await anon.post("/api/v1/auth/password", json={"current": PASSWORD, "new": "another-pass-1"})
    assert r.status_code == 200
    assert (await anon.post("/api/v1/auth/logout")).status_code == 200
    assert (await anon.get("/api/v1/accounts")).status_code == 401
    assert (await anon.login("another-pass-1")).status_code == 200


async def test_login_rate_limit(anon):
    from app.core.security import login_limiter

    login_limiter._fails.clear()
    await anon.get("/api/v1/auth/me")
    for _ in range(5):
        await anon.c.post("/api/v1/auth/login", json={"password": "wrong"})
    r = await anon.c.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert r.status_code == 429
    login_limiter._fails.clear()


async def test_spa_and_health(anon, env):
    import pathlib

    assert (await anon.get("/healthz")).json()["ok"] is True
    r = await anon.get("/api/v1/nope")
    assert r.status_code == 404 and r.json()["code"] == "not_found"
    assert (await anon.get("/accounts/x")).status_code == 503  # frontend not built in this test
    dist = pathlib.Path(env["FRONTEND_DIST"])
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>spa</html>")
    r = await anon.get("/accounts/psychonet/ads")
    assert r.status_code == 200 and "spa" in r.text
    assert "Content-Security-Policy" in r.headers


async def test_spa_assets_and_root_files(tmp_path):
    import httpx
    from fastapi import FastAPI

    from app.main import mount_spa

    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text("<html>spa</html>")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    app = FastAPI()
    mount_spa(app, tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/assets/index-abc123.js")
        assert r.status_code == 200 and "immutable" in r.headers["cache-control"]
        assert (await c.get("/favicon.svg")).text == "<svg/>"
        r = await c.get("/accounts/darvaze/settings")
        assert "spa" in r.text and r.headers["cache-control"] == "no-cache"
        assert (await c.get("/../../etc/passwd")).text == "<html>spa</html>"


# ---------------------------------------------------------------- accounts & connections


async def test_accounts_and_connections(api):
    r = await api.post("/api/v1/accounts", json={"name": "سایکونت", "slug": "Bad Slug"})
    assert r.status_code == 400
    acc = await make_account(api)
    assert acc["check"]["ok"] is True and acc["check"]["status"] == "ok"
    a = acc["account"]
    assert a["telegram"]["status"] == "ok" and a["telegram"]["currency"] == "TON"
    assert a["telegram"]["token_last4"] == "en-a" and "token" not in json.dumps(a["telegram"]).replace(
        "token_last4", ""
    )
    assert a["bot"]["base_url"] == BOT_BASE and a["bot"]["stats"]["count_user"] == 1500
    assert "transactions" in a["bot"]["fields"]
    # duplicate slug
    r = await api.post("/api/v1/accounts", json={"name": "x", "slug": "psychonet"})
    assert r.status_code == 409
    # invalid token -> error status, friendly message
    r = await api.put("/api/v1/accounts/psychonet/telegram", json={"token": "wrong-token-but-long-enough-1234"})
    assert r.status_code == 200 and r.json()["check"]["ok"] is False and "توکن" in r.json()["check"]["error"]
    # a bot key without the users permission -> partial (warn)
    r = await api.put(
        "/api/v1/accounts/psychonet/bot",
        json={"base_url": BOT_BASE, "username": "psychonet_test_bot", "api_key": "botkey-limited"},
    )
    chk = r.json()["check"]
    assert chk["status"] == "warn" and any(not c["ok"] for c in chk["checks"])
    # keep the stored key when api_key is omitted
    r = await api.put("/api/v1/accounts/psychonet/bot", json={"base_url": BOT_BASE, "username": "psychonet_test_bot"})
    assert r.json()["check"]["status"] == "warn"
    # settings validation and clamping
    r = await api.patch("/api/v1/accounts/psychonet", json={"settings": {"sync_fast_seconds": 0}})
    assert r.status_code == 200 and r.json()["settings"]["sync_fast_seconds"] >= 1
    r = await api.patch("/api/v1/accounts/psychonet", json={"settings": {"nope": 1}})
    assert r.status_code == 400
    r = await api.patch("/api/v1/accounts/psychonet", json={"settings": {"stop_cost_per_start": "abc"}})
    assert r.status_code == 400


async def test_two_accounts_are_isolated(api):
    await make_account(api)
    await make_account(
        api,
        slug="darvaze",
        name="دروازه آزادی",
        token="mocktoken-b",
        bot_key="botkey-b",
        bot_username="darvaze_test_bot",
    )
    await _sync_all("psychonet")
    await _sync_all("darvaze")
    a = (await api.get("/api/v1/accounts/psychonet/ads")).json()["ads"]
    b = (await api.get("/api/v1/accounts/darvaze/ads")).json()["ads"]
    assert len(a) == 12 and len(b) == 4
    assert {x["ad_id"] for x in a}.isdisjoint({x["ad_id"] for x in b})
    ov = (await api.get("/api/v1/overview")).json()["accounts"]
    assert [x["slug"] for x in ov] == ["psychonet", "darvaze"]
    assert all(x["summary"]["28"]["spent"] > 0 for x in ov)
    d = (await api.get("/api/v1/accounts/darvaze/dashboard")).json()
    assert d["summary"]["28"]["purchases"] > 0 and len(d["daily"]) == 60
    assert (await api.get("/api/v1/accounts/nobody/ads")).status_code == 404


# ---------------------------------------------------------------- sync, rules, actions


async def test_sync_rules_and_actions(api, tg_mock):
    await make_account(api)
    await _sync_all("psychonet")
    props = (await api.get("/api/v1/accounts/psychonet/proposals")).json()
    by_title = {p["title"]: p["kind"] for p in props["pending"]}
    assert by_title.get("stalled_a") == "withdraw" and by_title.get("stalled_b") == "withdraw"
    assert by_title.get("expensive") == "stop" and by_title.get("slow_expensive") == "stop"
    assert by_title.get("good_low_budget") == "topup" and by_title.get("good_bot_low_budget") == "topup"
    assert by_title.get("fatigued") == "refresh"
    assert by_title.get("refill_gap") == "refill" and by_title.get("declined_text") == "replace"
    assert not {"good_plenty", "old_stopped", "new_in_review"} & set(by_title)
    refill = next(p for p in props["pending"] if p["title"] == "refill_gap")
    assert "20 روز است بودجه ندارد" in refill["reason"] and refill["amount"] == 1.0
    replace = next(p for p in props["pending"] if p["title"] == "declined_text")
    assert "Misleading urgency" in replace["reason"]

    # reject -> not proposed again on the next run
    fat = next(p for p in props["pending"] if p["title"] == "fatigued")
    assert (await api.post(f"/api/v1/accounts/psychonet/proposals/{fat['id']}/reject")).status_code == 200
    await api.post("/api/v1/accounts/psychonet/proposals/run")
    again = (await api.get("/api/v1/accounts/psychonet/proposals")).json()["pending"]
    assert not any(p["title"] == "fatigued" for p in again)

    # approve top-ups first (balance too low until withdrawals land), then the rest
    for p in [p for p in again if p["kind"] == "topup"]:
        assert (await api.post(f"/api/v1/accounts/psychonet/proposals/{p['id']}/approve")).status_code == 200
    for kind in ("withdraw", "stop"):
        r = await api.post("/api/v1/accounts/psychonet/proposals/approve-kind", json={"kind": kind})
        assert r.status_code == 200 and r.json()["approved"] >= 2 and not r.json()["errors"]
    for _ in range(12):
        await actions.process_due()
        async with session_scope() as s:
            left = (await s.execute(select(Job).where(Job.status.in_(("queued", "running"))))).scalars().all()
            for j in left:  # skip the waiting time in tests
                j.run_at = 0
        if not left:
            break
    async with session_scope() as s:
        jobs = (await s.execute(select(Job))).scalars().all()
        assert jobs and all(j.status == "done" for j in jobs), [(j.kind, j.status, j.result) for j in jobs]
        props_db = (
            (await s.execute(select(Proposal).where(Proposal.status.in_(("approved", "pending"))))).scalars().all()
        )
        assert {p.kind for p in props_db if p.status == "pending"} <= {"refresh", "refill", "replace"}
    acct = tg_mock.accounts["a"]
    for ad_id in (4, 5, 6, 7):  # withdrawn/stopped ads are paused with nothing left
        assert acct["ads"][ad_id]["is_paused"] and acct["ads"][ad_id]["remaining_budget"] == 0
    assert acct["ads"][1]["remaining_budget"] > 0.1  # top-up landed after the withdrawals

    # caps
    r = await api.post("/api/v1/accounts/psychonet/ads/3/actions", json={"action": "topup", "amount": 50})
    assert r.status_code == 400 and "سقف" in r.json()["detail"]
    # kill switch
    r = await api.post("/api/v1/accounts/psychonet/kill", json={"confirm": "no"})
    assert r.status_code == 400
    r = await api.post("/api/v1/accounts/psychonet/kill", json={"confirm": "توقف"})
    assert r.status_code == 200
    await actions.process_due()
    assert all(a.get("is_paused") or a["status"] != "active" for a in acct["ads"].values())
    r = await api.post("/api/v1/accounts/psychonet/ads/3/actions", json={"action": "topup", "amount": 0.5})
    assert r.status_code == 400 and r.json()["code"] == "automation_paused"


# ---------------------------------------------------------------- referral tags & sales


async def test_referral_tags_attribution(api, bot_mock):
    await make_account(api)
    r = await api.post(
        "/api/v1/accounts/psychonet/tags", json={"name": "کانال الف", "referrer_id": "9001", "start_code": "ref_a1"}
    )
    assert r.status_code == 201
    r = await api.post(
        "/api/v1/accounts/psychonet/tags", json={"name": "dup", "referrer_id": "9002", "start_code": "ref_a1"}
    )
    assert r.status_code == 409
    r = await api.post("/api/v1/accounts/psychonet/tags", json={"name": "x", "referrer_id": "abc"})
    assert r.status_code == 400
    lookup = (await api.post("/api/v1/accounts/psychonet/tags/lookup", json={"referrer_id": "9001"})).json()
    assert lookup["ok"] and lookup["referred"] == 40
    await _sync_all("psychonet")
    tags = (await api.get("/api/v1/accounts/psychonet/tags")).json()["tags"]
    t = tags[0]
    assert t["users"] == 40 and t["referred_count"] == 40 and 0 < t["buyers"] <= 40
    assert t["link"] == "https://t.me/psychonet_test_bot?start=ref_a1"
    assert [a["title"] for a in t["ads"]] == ["good_low_budget"] and t["cpp"] is not None
    ads = {a["title"]: a for a in (await api.get("/api/v1/accounts/psychonet/ads")).json()["ads"]}
    assert ads["good_low_budget"]["tag_name"] == "کانال الف" and ads["good_low_budget"]["buyers"] == t["buyers"]
    assert ads["good_plenty"]["tag_id"] is None  # ref_a2 has no tag yet
    # a new user who buys shows up after the next bot sync
    bot_mock.add_user("a", "9001", buy=True)
    await sync.run(await _id("psychonet"), "bot")
    t2 = (await api.get("/api/v1/accounts/psychonet/tags")).json()["tags"][0]
    assert t2["users"] == 41 and t2["buyers"] == t["buyers"] + 1
    sales = (await api.get("/api/v1/accounts/psychonet/sales")).json()["overview"]
    assert any(x["type"] == "buy" for x in sales["by_type"])
    summ = (await api.get("/api/v1/accounts/psychonet/dashboard")).json()["summary"]
    assert 0 < summ["attributed_28"]["buyers"] <= t2["buyers"]  # 28-day window vs all time


async def test_bot_whose_unfiltered_ledger_crashes(api, bot_mock):
    """The bot answers HTTP 500 with a non-JSON body unless `type` is given (seen on the real bot)."""
    from app.integrations import bot_api

    bot_api._tx_shape.clear()
    acc = await make_account(
        api, slug="darvaze", name="دروازه", token="mocktoken-b", bot_key="botkey-crash", bot_username="darvaze_test_bot"
    )
    check = acc["check"]
    assert check["status"] == "ok", check
    tx = next(c for c in check["checks"] if c["name"] == "transactions")
    assert tx["ok"] and "فیلتر نوع خرید" in tx["message"] and "Fatal error" in tx["message"]
    r = await api.post("/api/v1/accounts/darvaze/tags", json={"name": "معرف", "referrer_id": "9101"})
    assert r.status_code == 201
    await _sync_all("darvaze")
    a = (await api.get("/api/v1/accounts/darvaze")).json()
    assert a["bot"]["status"] == "ok", a["bot"]
    assert a["bot"]["fields"]["transactions_mode"] == ["per_type"]
    sales = (await api.get("/api/v1/accounts/darvaze/sales")).json()
    types = {x["type"] for x in sales["overview"]["by_type"]}
    assert types and types <= {"buy", "buy_extend"}
    tag = sales["tags"][0]
    assert tag["users"] == 25 and tag["buyers"] > 0  # referrals in the obj.users shape

    # With purchase types cleared there is nothing to fall back to: the bot's own error is reported clearly.
    r = await api.patch("/api/v1/accounts/darvaze", json={"settings": {"purchase_types": ["refund"]}})
    assert r.status_code == 200
    bot_api._tx_shape.clear()
    bot_mock.data["b"]["txs"] = [t for t in bot_mock.data["b"]["txs"] if t["type"] != "refund"]
    check = (await api.post("/api/v1/accounts/darvaze/bot/check")).json()["check"]
    assert check["status"] == "ok"  # per-type query for "refund" works (zero rows)


async def test_bot_server_error_message_is_readable():
    import httpx

    from app.integrations.bot_api import BotApiClient, BotApiError

    def crash(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="<br />\n<b>Fatal error</b>: boom in /var/www/api/users.php:10")

    async with httpx.AsyncClient(transport=httpx.MockTransport(crash)) as http:
        c = BotApiClient("https://bot.example", "secret-key", http=http)
        try:
            await c.transactions(limit=5)
        except BotApiError as e:
            assert e.http_status == 500
            assert "Fatal error: boom" in e.friendly and "توسعه‌دهنده" in e.friendly
            assert "secret-key" not in e.friendly
        else:
            raise AssertionError("expected an error")


# ---------------------------------------------------------------- ads


async def test_create_and_edit_ads(api, tg_mock):
    await make_account(api)
    await api.post(
        "/api/v1/accounts/psychonet/tags", json={"name": "t", "referrer_id": "9002", "start_code": "ref_new"}
    )
    tag_id = (await api.get("/api/v1/accounts/psychonet/tags")).json()["tags"][0]["id"]
    tg_mock.accounts["a"]["account"]["remaining_budget"] = 10
    base = {
        "kind": "channel",
        "username": "@newvpnchannel",
        "text": "سایکونت | تست رایگان 👇",
        "cpm": 0.45,
        "budget": 1,
    }

    async def create(**over):
        return await api.post("/api/v1/accounts/psychonet/ads", data={"payload": json.dumps({**base, **over})})

    assert (await create(text="x" * 161)).status_code == 400
    assert (await create(text="[مدت] تست")).status_code == 400
    assert (await create(username="@badchannel")).status_code == 400
    r = await api.post(
        "/api/v1/accounts/psychonet/ads",
        data={"payload": json.dumps({**base, "tag_id": tag_id})},
        files={"photo": ("p.jpg", b"\xff\xd8fake", "image/jpeg")},
    )
    assert r.status_code == 201, r.text
    ad_id = r.json()["ad_id"]
    raw = tg_mock.accounts["a"]["ads"][ad_id]
    assert raw["promote_url"] == "https://t.me/psychonet_test_bot?start=ref_new" and raw.get("photo")
    async with session_scope() as s:
        ad = (await s.execute(select(Ad).where(Ad.ad_id == ad_id))).scalar_one()
        assert ad.tag_id == tag_id and ad.created_by_app
    # edit text -> goes to Telegram and back to review
    r = await api.patch(f"/api/v1/accounts/psychonet/ads/{ad_id}", json={"text": "متن تازه 👇"})
    assert r.status_code == 200 and r.json()["remote_changed"] is True
    assert raw["text"] == "متن تازه 👇" and raw["status"] == "in_review"
    # remove the tracking tag
    r = await api.patch(f"/api/v1/accounts/psychonet/ads/{ad_id}", json={"clear_tag": True})
    assert r.status_code == 200 and raw["promote_url"] == "https://t.me/psychonet_test_bot"
    # note only -> local
    r = await api.patch(f"/api/v1/accounts/psychonet/ads/{ad_id}", json={"note": "یادداشت"})
    assert r.json()["remote_changed"] is False
    detail = (await api.get(f"/api/v1/accounts/psychonet/ads/{ad_id}")).json()
    assert detail["ad"]["note"] == "یادداشت" and detail["ad"]["tag_id"] is None


# ---------------------------------------------------------------- texts & Claude


async def test_texts_and_claude(api):
    await make_account(api)
    await _sync_all("psychonet")
    r = await api.post("/api/v1/accounts/psychonet/texts", json={"name": "الف", "text": "y" * 161})
    assert r.status_code == 400
    r = await api.post("/api/v1/accounts/psychonet/texts", json={"name": "الف", "text": "سایکونت | VPN 👇"})
    assert r.status_code == 201
    vid = r.json()["id"]
    imported = (await api.post("/api/v1/accounts/psychonet/texts/import")).json()["imported"]
    assert imported == 2  # the shared test text and the declined ad's text
    texts = (await api.get("/api/v1/accounts/psychonet/texts")).json()["texts"]
    imported_text = next(t for t in texts if t["source"] == "imported" and t["text"] == "متن آزمایشی آگهی 👇")
    assert imported_text["performance"]["ads"] == 11
    # Claude without a key
    r = await api.post(f"/api/v1/accounts/psychonet/texts/{vid}/analyze", json={})
    assert r.status_code == 400 and r.json()["code"] == "claude_error"
    r = await api.put("/api/v1/settings", json={"claude_api_key": "sk-ant-test", "ui_refresh_seconds": 3})
    assert r.json()["claude_key_set"] is True and r.json()["claude_key_last4"] == "test"
    assert (await api.post("/api/v1/settings/claude/test")).json()["ok"] is True
    res = (await api.post(f"/api/v1/accounts/psychonet/texts/{vid}/analyze", json={"goal": "فروش بیشتر"})).json()
    assert res["score"] == 62 and len(res["rewrites"]) == 3
    assert [r["too_long"] for r in res["rewrites"]] == [False, True, False]
    # manual edit; a text in use by an ad becomes a new version
    r = await api.patch(f"/api/v1/accounts/psychonet/texts/{vid}", json={"text": "ویرایش دستی 👇"})
    assert r.status_code == 200 and r.json()["versioned"] is False and r.json()["text"] == "ویرایش دستی 👇"
    async with session_scope() as s:
        ad = (await s.execute(select(Ad).where(Ad.ad_id == 3))).scalar_one()
        ad.variant_id = vid
    r = await api.patch(f"/api/v1/accounts/psychonet/texts/{vid}", json={"text": "نسخه‌ی دوم 👇"})
    assert r.json()["versioned"] is True and r.json()["id"] != vid
    # account analysis + export
    r = await api.post("/api/v1/accounts/psychonet/analysis", json={"question": ""})
    assert r.status_code == 200 and "تحلیل" in r.json()["output"]
    assert len((await api.get("/api/v1/accounts/psychonet/analysis")).json()["analyses"]) == 1
    r = await api.get("/api/v1/accounts/psychonet/export.zip")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert set(z.namelist()) == {"ads.csv", "daily_ad_stats.csv", "bot_transactions.csv", "context.json", "PROMPT.txt"}


async def test_live_and_activity(api):
    await make_account(api)
    await _sync_all("psychonet")
    live = (await api.get("/api/v1/accounts/psychonet/live")).json()
    assert live["account"]["sync"]["fast"]["last_ok"] and live["ui_refresh_seconds"] == 5
    assert "today" in live["live"]
    act = (await api.get("/api/v1/accounts/psychonet/activity")).json()
    assert any(e["action"] == "account_created" for e in act["events"])
    sysinfo = (await api.get("/api/v1/system")).json()
    assert sysinfo["server_ip"] == "203.0.113.7"
    r = await api.post("/api/v1/accounts/psychonet/sync", json={"kind": "fast"})
    assert r.status_code == 200
