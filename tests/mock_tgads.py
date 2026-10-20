"""A small fake Telegram Ads API for testing the app without touching real money.

Usage: python tests/mock_tgads.py [port] [seed.json] [daily.csv]
Seed files are optional; without them it starts with made-up ads that cover every rule.
"""
import csv
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

INACTIVE_SECONDS = float(__import__("os").environ.get("MOCK_INACTIVE_SECONDS", "3"))
STATE = {"account": {"account_id": "mock", "title": "Mock", "currency": "TON", "spent_budget": 10.0,
                     "remaining_budget": 5.0, "ads_budget": 0.0},
         "ads": {}, "stats": {}, "paused_at": {}, "next_id": 1000, "idem": {}}


SCENARIOS = [
    # (name, placement, cpm, days_running, starts_per_TON_early, starts_per_TON_late, daily_spend, quiet_days, remaining)
    ("good_low_budget", "channel_post", 0.45, 60, 90, 90, 0.05, 0, 0.1),
    ("good_bot_low_budget", "bot_banner", 0.5, 60, 70, 70, 0.04, 0, 0.05),
    ("good_plenty", "channel_post", 0.45, 50, 80, 80, 0.03, 0, 3.0),
    ("stalled_a", "channel_post", 0.45, 90, 120, 120, 0.06, 45, 2.4),
    ("stalled_b", "bot_banner", 0.5, 90, 80, 80, 0.05, 40, 1.3),
    ("expensive", "channel_post", 0.2, 60, 12, 12, 0.06, 0, 1.2),
    ("slow_expensive", "channel_post", 0.2, 120, 8, 8, 0.012, 0, 0.8),
    ("fatigued", "channel_post", 0.45, 45, 100, 30, 0.05, 0, 2.0),
    ("new_in_review", "channel_post", 0.45, 0, 0, 0, 0, 0, 1.0),
    ("old_stopped", "channel_post", 0.45, 120, 50, 50, 0.08, 60, 0.0),
]


def _synthetic():
    """Made-up ads covering every rule, so tests never need real campaign data."""
    import random
    rnd = random.Random(7)
    today = datetime.now(timezone.utc).date()
    for i, (name, placement, cpm, days, early, late, spend, quiet, remaining) in enumerate(SCENARIOS, start=1):
        created = today - timedelta(days=max(days, 1))
        rows, tot = [], {"views": 0, "clicks": 0, "actions": 0, "spent": 0.0}
        for d in range(days):
            day = created + timedelta(days=d)
            if day > today or (quiet and day > today - timedelta(days=quiet)):
                continue
            sp = round(spend * rnd.uniform(0.6, 1.4), 5)
            rate = early if d < days / 2 else late
            starts = int(sp * rate * rnd.uniform(0.8, 1.2))
            views = int(sp / cpm * 1000)
            clicks = max(starts, int(views * 0.03))
            rows.append({"date": day.isoformat(), "views": views, "clicks": clicks, "actions": starts, "spent": sp})
            for k, v in (("views", views), ("clicks", clicks), ("actions", starts), ("spent", sp)):
                tot[k] += v
        status = "in_review" if name == "new_in_review" else "stopped" if name == "old_stopped" else "active"
        key = "bots" if placement == "bot_banner" else "channels"
        STATE["ads"][i] = {
            "ad_id": i, "title": name, "text": "sample ad text", "promote_url": "https://t.me/samplebot",
            "cpm": cpm, "placement": placement, "status": status, "views": tot["views"], "clicks": tot["clicks"],
            "actions": tot["actions"], "action_type": "start_bot", "spent_budget": round(tot["spent"], 5),
            "remaining_budget": remaining, "currency": "TON",
            "created_date": int(datetime.combine(created, datetime.min.time(), timezone.utc).timestamp()),
            "target": {"type": key, key: [{"username": f"sample_{name}", "title": name}]}}
        STATE["stats"][i] = rows
    STATE["account"]["spent_budget"] = round(sum(a["spent_budget"] for a in STATE["ads"].values()), 5)
    STATE["account"]["remaining_budget"] = 0.05  # like a real account after a campaign: money sits on the ads


def seed(raw_path=None, daily_path=None):
    if raw_path:
        raw = json.load(open(raw_path, encoding="utf-8"))
        STATE["account"].update(raw["account"])
        for a in raw["ads"]:
            STATE["ads"][a["ad_id"]] = a
        if daily_path:
            for r in csv.DictReader(open(daily_path, encoding="utf-8-sig")):
                STATE["stats"].setdefault(int(r["ad_id"]), []).append(r)
    else:
        _synthetic()
    STATE["account"]["ads_budget"] = round(sum(a.get("remaining_budget", 0) for a in STATE["ads"].values()), 5)


def day_ts(d):
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def handle(method, p, files):
    acct, ads = STATE["account"], STATE["ads"]
    if method == "getCurrentAccount":
        return acct
    if method == "getAdsList":
        items = sorted(ads.values(), key=lambda a: -a["ad_id"])
        off = int(p.get("offset") or 0)
        lim = int(p.get("limit") or 100)
        page = items[off:off + lim]
        res = {"total_count": len(items), "ads": page}
        if off + lim < len(items):
            res["next_offset"] = str(off + lim)
        return res
    if method == "getAdsById":
        ids = p["ad_ids"] if isinstance(p["ad_ids"], list) else json.loads(p["ad_ids"])
        return [ads[i] for i in ids if i in ads]
    if method == "getAdStats":
        aid = int(p["ad_id"])
        out = []
        for r in STATE["stats"].get(aid, []):
            ts = day_ts(r["date"])
            if int(p["from_time"]) <= ts < int(p["to_time"]):
                out.append({"from_time": ts, "to_time": ts + 86400, "views": int(r["views"]), "clicks": int(r["clicks"]),
                            "actions": int(r["actions"]), "opens": 0, "spent_budget": float(r["spent"]), "currency": "TON"})
        return out
    if method == "editAd":
        a = ads.get(int(p["ad_id"]))
        if not a:
            raise KeyError("AD_ID_INVALID")
        if "is_paused" in p:
            paused = p["is_paused"] in (True, "true", "True", 1, "1")
            a["is_paused"] = paused
            if paused:
                STATE["paused_at"][a["ad_id"]] = time.time()
            else:
                STATE["paused_at"].pop(a["ad_id"], None)
        return a
    if method == "decreaseAdBudget":
        a = ads[int(p["ad_id"])]
        if not a.get("is_paused") or time.time() - STATE["paused_at"].get(a["ad_id"], time.time()) < INACTIVE_SECONDS:
            raise KeyError("AD_ACTIVE_RECENTLY")
        amt = float(p["amount"])
        if amt > a["remaining_budget"] + 1e-9:
            raise KeyError("NOT_ENOUGH_BUDGET")
        a["remaining_budget"] = round(a["remaining_budget"] - amt, 5)
        acct["remaining_budget"] = round(acct["remaining_budget"] + amt, 5)
        acct["ads_budget"] = round(acct["ads_budget"] - amt, 5)
        return a
    if method == "increaseAdBudget":
        a = ads[int(p["ad_id"])]
        amt = float(p["amount"])
        if amt > acct["remaining_budget"] + 1e-9:
            raise KeyError("NOT_ENOUGH_BUDGET")
        a["remaining_budget"] = round(a["remaining_budget"] + amt, 5)
        acct["remaining_budget"] = round(acct["remaining_budget"] - amt, 5)
        acct["ads_budget"] = round(acct["ads_budget"] + amt, 5)
        return a
    if method in ("getTargetChannel", "getTargetBot"):
        u = str(p.get("channel_id") or p.get("bot_id"))
        if "bad" in u.lower():
            raise KeyError("CHANNEL_INVALID")
        return {"channel_id": 1, "username": u.lstrip("@"), "title": u}
    if method == "uploadAdPhoto":
        if "file" not in files:
            raise KeyError("FILE_REQUIRED")
        return {"photo_id": "ph_" + str(len(files["file"])), "photo_url": "https://example.invalid/p.jpg"}
    if method == "createAd":
        budget = float(p.get("initial_budget") or 0)
        if budget > acct["remaining_budget"] + 1e-9:
            raise KeyError("NOT_ENOUGH_BUDGET")
        if len(p["text"]) > 160:
            raise KeyError("AD_TEXT_TOO_LONG")
        STATE["next_id"] += 1
        aid = STATE["next_id"]
        t = p["target"]
        names = t.get("channel_ids") or t.get("bot_ids") or []
        key = "channels" if t["type"] == "channels" else "bots"
        ad = {"ad_id": aid, "title": p["title"], "text": p["text"], "promote_url": p["promote_url"], "cpm": float(p["cpm"]),
              "placement": p["placement"], "status": "in_review", "views": 0, "clicks": 0, "actions": 0,
              "spent_budget": 0, "remaining_budget": budget, "created_date": int(time.time()), "currency": "TON",
              "target": {"type": t["type"], key: [{"username": n.lstrip("@"), "title": n} for n in names]}}
        if p.get("photo_id"):
            ad["photo"] = {"photo_id": p["photo_id"]}
        ads[aid] = ad
        acct["remaining_budget"] = round(acct["remaining_budget"] - budget, 5)
        acct["ads_budget"] = round(acct["ads_budget"] + budget, 5)
        return ad
    raise KeyError("METHOD_NOT_FOUND")


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.headers.get("Authorization") != "Bearer mocktoken":
            return self._send({"ok": False, "error": "ACCESS_TOKEN_INVALID"})
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        ctype = self.headers.get("Content-Type", "")
        files, params = {}, {}
        if ctype.startswith("multipart/"):
            boundary = ctype.split("boundary=")[1].encode()
            for part in body.split(b"--" + boundary):
                if b"Content-Disposition" not in part:
                    continue
                head, _, data = part.partition(b"\r\n\r\n")
                name = head.split(b'name="')[1].split(b'"')[0].decode()
                if b"filename=" in head:
                    files[name] = data.rstrip(b"\r\n")
                else:
                    params[name] = data.rstrip(b"\r\n").decode()
        else:
            params = json.loads(body or b"{}")
        key = self.headers.get("Idempotency-Key")
        method = self.path.strip("/")
        if key and key in STATE["idem"]:
            return self._send(STATE["idem"][key])
        try:
            res = {"ok": True, "result": handle(method, params, files)}
        except KeyError as e:
            res = {"ok": False, "error": str(e.args[0])}
        if key and res["ok"]:
            STATE["idem"][key] = res
        self._send(res)

    def _send(self, obj):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8790
    seed(sys.argv[2] if len(sys.argv) > 2 else None, sys.argv[3] if len(sys.argv) > 3 else None)
    print(f"mock Telegram Ads API on http://127.0.0.1:{port} (token: mocktoken)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
