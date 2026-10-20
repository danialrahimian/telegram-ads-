"""Pull the account, every ad and daily stats from Telegram Ads into SQLite."""
import json
import time
from datetime import datetime, timezone

from . import db
from .tgads import client as tg_client

DAY = 86400


def target_summary(t):
    if not t:
        return "", ""
    typ = t.get("type", "")
    parts = []
    for key in ("channels", "bots"):
        for x in t.get(key) or []:
            parts.append("@" + x["username"] if x.get("username") else (x.get("title") or str(x.get("channel_id") or x.get("bot_id"))))
    if t.get("search_queries"):
        parts.append("جست‌وجو: " + "، ".join(t["search_queries"]))
    for key, label in (("topics", "موضوع"), ("languages", "زبان"), ("countries", "کشور")):
        if t.get(key):
            parts.append(label + ": " + "، ".join(x.get("name", "") for x in t[key]))
    return typ, " | ".join(parts)


def _day(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def run(client=None, log_actor="sync"):
    c = client or tg_client()
    started = time.time()
    acct = c.account()
    ads = c.ads()
    prev = {r["ad_id"]: r for r in db.query("SELECT ad_id, spent_budget, synced_at FROM ads")}
    have_stats = {r["ad_id"] for r in db.query("SELECT DISTINCT ad_id FROM stats")}
    now = db.now()

    with db.tx() as t:
        t.execute("""INSERT INTO account(id, title, currency, spent_budget, remaining_budget, ads_budget, synced_at)
                     VALUES (1, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,
                     currency=excluded.currency, spent_budget=excluded.spent_budget,
                     remaining_budget=excluded.remaining_budget, ads_budget=excluded.ads_budget, synced_at=excluded.synced_at""",
                  (acct.get("title"), acct.get("currency"), acct.get("spent_budget"), acct.get("remaining_budget"),
                   acct.get("ads_budget"), now))
        seen = []
        for a in ads:
            typ, label = target_summary(a.get("target"))
            seen.append(a["ad_id"])
            t.execute("""INSERT INTO ads(ad_id, title, text, promote_url, cpm, placement, status, is_paused, views, clicks,
                         actions, action_type, spent_budget, remaining_budget, created_date, target_type, target_label,
                         target_json, has_photo, has_video, show_userpic, decline_reason, synced_at, gone)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0)
                         ON CONFLICT(ad_id) DO UPDATE SET title=excluded.title, text=excluded.text,
                         promote_url=excluded.promote_url, cpm=excluded.cpm, placement=excluded.placement,
                         status=excluded.status, is_paused=excluded.is_paused, views=excluded.views,
                         clicks=excluded.clicks, actions=excluded.actions, action_type=excluded.action_type,
                         spent_budget=excluded.spent_budget, remaining_budget=excluded.remaining_budget,
                         created_date=excluded.created_date, target_type=excluded.target_type,
                         target_label=excluded.target_label, target_json=excluded.target_json,
                         has_photo=excluded.has_photo, has_video=excluded.has_video,
                         show_userpic=excluded.show_userpic, decline_reason=excluded.decline_reason,
                         synced_at=excluded.synced_at, gone=0""",
                      (a["ad_id"], a.get("title"), a.get("text"), a.get("promote_url"), a.get("cpm"), a.get("placement"),
                       a.get("status"), 1 if a.get("is_paused") else 0, a.get("views", 0), a.get("clicks", 0),
                       a.get("actions", a.get("joins", 0)), a.get("action_type"), a.get("spent_budget", 0),
                       a.get("remaining_budget", 0), a.get("created_date"), typ, label,
                       json.dumps(a.get("target") or {}, ensure_ascii=False), 1 if a.get("photo") else 0,
                       1 if a.get("video") else 0, 1 if a.get("show_userpic") else 0,
                       (a.get("decline_reason") or {}).get("text"), now))
        if seen:
            t.execute(f"UPDATE ads SET gone=1 WHERE ad_id NOT IN ({','.join('?' * len(seen))})", seen)

    # Daily stats: refresh recent days for anything that is running or whose spend moved.
    to_time = (now // DAY + 1) * DAY
    fetched, errors = 0, []
    for a in ads:
        aid = a["ad_id"]
        moving = a.get("status") in ("active", "on_hold", "in_review") or \
            aid not in prev or abs((prev[aid]["spent_budget"] or 0) - (a.get("spent_budget") or 0)) > 1e-9
        if aid in have_stats and not moving:
            continue
        last = db.one("SELECT MAX(day) AS d FROM stats WHERE ad_id=?", (aid,))["d"]
        if last:
            start = int(datetime.strptime(last, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) - 2 * DAY
        else:
            start = a.get("created_date") or (now - 90 * DAY)
        start = max(start - start % DAY, to_time - 999 * DAY)
        try:
            items = c.ad_stats_daily(aid, start, to_time)
        except Exception as e:  # one bad ad should not stop the sync
            errors.append(f"{aid}: {e}")
            continue
        fetched += 1
        with db.tx() as t:
            for s in items:
                t.execute("""INSERT INTO stats(ad_id, day, views, clicks, actions, spent) VALUES (?,?,?,?,?,?)
                             ON CONFLICT(ad_id, day) DO UPDATE SET views=excluded.views, clicks=excluded.clicks,
                             actions=excluded.actions, spent=excluded.spent""",
                          (aid, _day(s["from_time"]), s.get("views", 0), s.get("clicks", 0),
                           s.get("actions", s.get("joins", 0)), s.get("spent_budget", 0)))
        time.sleep(0.15)

    db.set_setting("last_sync", {"at": now, "ads": len(ads), "stats_fetched": fetched,
                                 "errors": errors[:20], "seconds": round(time.time() - started, 1)})
    db.log(log_actor, "sync", None, f"{len(ads)} آگهی، آمار {fetched} آگهی به‌روز شد" + (f"، {len(errors)} خطا" if errors else ""))
    return {"ads": len(ads), "stats": fetched, "errors": errors}
