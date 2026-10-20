"""End-to-end check of the whole app against tests/mock_tgads.py (synthetic data, no real money).

Run the mock and the app first (see tests/run_e2e.sh), then: python tests/e2e.py <data_dir>
Exits non-zero on the first failed check.
"""
import io
import json
import re
import sqlite3
import sys
import time
import zipfile

import httpx

DATA = sys.argv[1]
B = "http://127.0.0.1:8800"
MOCK = "http://127.0.0.1:8790"
c = httpx.Client(base_url=B, follow_redirects=True, timeout=120)


def csrf(html):
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def flashes(html, kind="(?:ok|bad)"):
    return re.findall(rf'class="flash {kind}">([^<]+)', html)


def mock(method, **p):
    return httpx.post(f"{MOCK}/{method}", headers={"Authorization": "Bearer mocktoken"}, json=p).json()["result"]


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)
    print("ok  ", msg)


db = sqlite3.connect(DATA + "/app.db", timeout=30)

# login, rate of wrong password, CSRF
r = c.get("/")
check("/login" in str(r.url), "anonymous user is sent to login")
r = c.post("/login", data={"password": "wrong", "csrf": csrf(r.text)})
check(r.status_code == 401, "wrong password refused")
r = c.post("/login", data={"password": "test-password-123", "csrf": csrf(r.text)})
check(r.status_code == 200 and "نمای کلی" in r.text, "login works")
tok = csrf(r.text)
r = c.post("/rules-run", data={"csrf": "nope"})
check(flashes(r.text, "bad") and "/login" not in str(r.url), "stale CSRF token refused without logging out")

# first sync (scheduler starts it on boot)
t0 = time.time()
while time.time() - t0 < 90 and not db.execute("select count(*) from ads").fetchone()[0]:
    time.sleep(2)
while time.time() - t0 < 90 and not db.execute("select value from settings where key='last_sync'").fetchone():
    time.sleep(2)
check(db.execute("select count(*) from ads").fetchone()[0] == 10, "sync stored all ads")
check(db.execute("select count(*) from stats").fetchone()[0] > 400, "sync stored daily stats")

r = c.post("/rules-run", data={"csrf": tok})
kinds = dict(db.execute("select kind, count(*) from proposals where status='pending' group by kind").fetchall())
by_ad = {t: k for t, k in db.execute(
    "select a.title, p.kind from proposals p join ads a using(ad_id) where p.status='pending'")}
print("     proposals:", by_ad)
check(by_ad.get("stalled_a") == "withdraw" and by_ad.get("stalled_b") == "withdraw", "stalled ads -> withdraw")
check(by_ad.get("expensive") == "stop", "expensive ad -> stop")
check(by_ad.get("slow_expensive") == "stop", "slow expensive ad -> stop (lifetime rule)")
check(by_ad.get("good_low_budget") == "topup" and by_ad.get("good_bot_low_budget") == "topup", "good ads low on budget -> topup")
check(by_ad.get("fatigued") == "refresh", "fatigued ad -> refresh")
check("good_plenty" not in by_ad and "old_stopped" not in by_ad and "new_in_review" not in by_ad, "no proposal for healthy/stopped/new ads")

for p in ["/", "/ads", "/ads?show=all&since=2026-01-01", "/ads?show=attention", "/proposals", "/new", "/new?from=3",
          "/variants", "/conversions", "/analysis", "/settings", "/log", "/ads/3", "/ads/9999"]:
    r = c.get(p)
    check(r.status_code == 200 and "Traceback" not in r.text, f"page {p}")

# reject -> stays rejected after the next rules run
pid = db.execute("select p.id from proposals p join ads a using(ad_id) where a.title='fatigued' and p.status='pending'").fetchone()[0]
c.post(f"/proposals/{pid}/reject", data={"csrf": tok})
c.post("/rules-run", data={"csrf": tok})
check(not db.execute("select 1 from proposals p join ads a using(ad_id) where a.title='fatigued' and p.status='pending'").fetchone(),
      "rejected proposal is not re-proposed right away")

# approve: topups first (balance is too low until withdrawals land), then stops and withdrawals
for (pid,) in db.execute("select id from proposals where status='pending' and kind='topup'").fetchall():
    c.post(f"/proposals/{pid}/approve", data={"csrf": tok})
for k in ("withdraw", "stop"):
    r = c.post("/proposals-approve-kind", data={"csrf": tok, "kind": k})
    check(flashes(r.text, "ok"), f"approve all {k}")

t0 = time.time()
while time.time() - t0 < 180 and db.execute("select count(*) from jobs where status in ('queued','running')").fetchone()[0]:
    time.sleep(3)
jobs = db.execute("select kind, status, count(*) from jobs group by kind, status").fetchall()
print("     jobs:", jobs, round(time.time() - t0), "s")
check(not db.execute("select 1 from jobs where status!='done'").fetchone(), "every job finished")
ids = [x[0] for x in db.execute("select distinct ad_id from jobs where kind='withdraw'")]
check(all(a["remaining_budget"] == 0 and a.get("is_paused") for a in mock("getAdsById", ad_ids=ids)), "withdrawn ads are paused with zero budget")
top = mock("getAdsById", ad_ids=[1, 2])
check(top[0]["remaining_budget"] > 0.1 and top[1]["remaining_budget"] > 0.05, "topups landed after the withdrawals")
check(not db.execute("select 1 from proposals where status in ('pending','approved','failed') and kind!='refresh'").fetchone(),
      "approved proposals marked done")

# caps
r = c.post("/ads/3/action", data={"csrf": tok, "action": "topup", "amount": "50"})
check(any("سقف" in f for f in flashes(r.text, "bad")), "top-up above the per-ad cap refused")

# new ad
tok = csrf(c.get("/new").text)
base = {"csrf": tok, "kind": "channel", "username": "@newvpnchannel", "variant_id": "2", "cpm": "0.45", "budget": "1", "code": ""}
v2 = db.execute("select text from variants where id=2").fetchone()[0]
check(flashes(c.post("/new", data=dict(base, text="x" * 161)).text, "bad"), "text over 160 chars refused")
check(flashes(c.post("/new", data=dict(base, text="[مدت] تست")).text, "bad"), "placeholder text refused")
check(flashes(c.post("/new", data=dict(base, text=v2, budget="0")).text, "bad"), "zero budget refused")
check(flashes(c.post("/new", data=dict(base, text=v2, username="@badchannel")).text, "bad"), "unknown channel refused")
r = c.post("/new", data=dict(base, text=v2), files={"photo": ("p.jpg", b"\xff\xd8fake", "image/jpeg")})
check(flashes(r.text, "ok") and "/ads/" in str(r.url), "channel ad created")
r = c.post("/new", data=dict(base, kind="bot", username="@somevpnbot", cpm="0.5", show_userpic="1",
                             replace_ad_id="3", text=v2 + " ویرایش‌شده"))
check(flashes(r.text, "ok"), "bot ad created, replacing ad 3")
new = mock("getAdsList")["ads"][:2]
check(new[0]["placement"] == "bot_banner" and new[0]["promote_url"].startswith("https://t.me/sychonetbot?start=b_somevpnbot_"),
      "bot ad has its tracking link")
check(new[1].get("photo") and new[1]["target"]["channels"][0]["username"] == "newvpnchannel", "channel ad has photo and target")
meta = dict(db.execute("select ad_id, variant_id from ad_meta where created_by_app=1").fetchall())
check(meta[new[1]["ad_id"]] == 2 and meta[new[0]["ad_id"]] is None, "only unedited text counts toward its variant")
check(db.execute("select count(*) from jobs where ad_id=3 and kind in ('pause','withdraw')").fetchone()[0] == 2,
      "replaced ad queued for pause + withdraw")
code = db.execute("select code from ad_meta where ad_id=?", (new[1]["ad_id"],)).fetchone()[0]

# conversions
h = {"Authorization": "Bearer conv-secret-xyz"}
r = httpx.post(B + "/api/conversions", headers=h, json={"code": code, "event": "start", "id": "start-1"}).json()
check(r["added"] == 1, "API: start event recorded")
r = httpx.post(B + "/api/conversions", headers=h, json={"events": [
    {"code": code, "event": "purchase", "amount": 59000, "id": "o1"},
    {"code": code, "event": "purchase", "amount": 59000, "id": "o1"}, {"code": "", "event": "purchase"}, "junk"]}).json()
check(r["added"] == 1 and r["duplicates"] == 1 and len(r["errors"]) == 2, "API: duplicate ignored, bad rows reported")
check(httpx.post(B + "/api/conversions", headers={"Authorization": "Bearer wrong"}, json={}).status_code == 401, "API: wrong secret refused")
check(httpx.post(B + "/api/conversions", headers=h, json="x").status_code == 400, "API: bad body refused")
tok = csrf(c.get("/conversions").text)
r = c.post("/conversions/import", data={"csrf": tok}, files={"file": (
    "s.csv", f"code,event,amount,id,ts\n{code},purchase,59000,o1,\n{code},purchase,59000,o2,2026-01-05\nunknown_code,purchase,,o3,1700000000\n",
    "text/csv")})
check("2 رویداد" in (flashes(r.text) or [""])[0], "CSV import dedupes against API ids")
check("unknown_code" in c.get("/conversions").text, "unattached codes are listed")

# export
z = zipfile.ZipFile(io.BytesIO(c.get("/analysis/export.zip").content))
check(set(z.namelist()) == {"ads.csv", "daily.csv", "conversions.csv", "summary.json", "PROMPT.txt"}, "export bundle")
check(len(json.loads(z.read("summary.json"))["ads"]) >= 5, "export summary has the recent ads")

# settings
r = c.post("/settings", data={"csrf": tok, "stop_cost_per_start": "0.05", "sync_interval_minutes": "5"})
vals = dict(db.execute("select key, value from settings where key in ('stop_cost_per_start','sync_interval_minutes')").fetchall())
check(vals == {"stop_cost_per_start": "0.05", "sync_interval_minutes": "15"}, "settings saved, sync interval floored at 15")
check(flashes(c.post("/settings/kill", data={"csrf": tok, "confirm": "no"}).text, "bad"), "kill switch needs the confirm word")
r = c.post("/settings/kill", data={"csrf": tok, "confirm": "توقف"})
time.sleep(20)
running = [a for a in mock("getAdsList")["ads"] if a["status"] == "active" and not a.get("is_paused")]
check(not running, "kill switch paused every running ad")
check(c.post("/ads/1/action", data={"csrf": tok, "action": "topup", "amount": "0.5"}).text.count("متوقف است") >= 1,
      "actions blocked while paused")
r = c.post("/logout", data={"csrf": tok})
check("/login" in str(r.url), "logout")
print("ALL CHECKS PASSED")
