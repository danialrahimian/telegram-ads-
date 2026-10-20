"""Per-ad numbers used by the pages and the rules. All money is in the account currency (TON)."""
from datetime import date, datetime, timedelta, timezone

from . import db


def today():
    return datetime.now(timezone.utc).date()


def _ratio(a, b):
    return (a / b) if b else None


def window_totals(since_day, until_day=None):
    """Sum of stats per ad from since_day (inclusive) to until_day (inclusive)."""
    until_day = until_day or "9999-12-31"
    rows = db.query("""SELECT ad_id, SUM(views) v, SUM(clicks) c, SUM(actions) a, SUM(spent) s
                       FROM stats WHERE day >= ? AND day <= ? GROUP BY ad_id""", (since_day, until_day))
    return {r["ad_id"]: {"views": r["v"] or 0, "clicks": r["c"] or 0, "starts": r["a"] or 0, "spent": r["s"] or 0.0}
            for r in rows}


def conversions_by_code():
    rows = db.query("""SELECT code, SUM(CASE WHEN event='purchase' THEN 1 ELSE 0 END) p,
                       SUM(CASE WHEN event='purchase' THEN COALESCE(amount,0) ELSE 0 END) rev,
                       SUM(CASE WHEN event='start' THEN 1 ELSE 0 END) st
                       FROM conversions GROUP BY code""")
    return {r["code"]: {"purchases": r["p"] or 0, "revenue": r["rev"] or 0, "bot_starts": r["st"] or 0} for r in rows}


def ad_rows(since_day=None):
    """Every ad with lifetime, last-7, last-28 and optional since-day metrics."""
    t = today()
    d7 = (t - timedelta(days=6)).isoformat()
    d28 = (t - timedelta(days=27)).isoformat()
    w7, w28 = window_totals(d7), window_totals(d28)
    ws = window_totals(since_day) if since_day else {}
    first = {r["ad_id"]: r for r in db.query(
        "SELECT ad_id, MIN(day) first_day, MAX(CASE WHEN spent > 0 THEN day END) last_spend FROM stats GROUP BY ad_id")}
    meta = {r["ad_id"]: r for r in db.query("SELECT * FROM ad_meta")}
    conv = conversions_by_code()
    out = []
    for a in db.query("SELECT * FROM ads WHERE gone=0 ORDER BY ad_id DESC"):
        aid = a["ad_id"]
        m = meta.get(aid, {})
        code = m.get("code") or ""
        cv = conv.get(code, {}) if code else {}
        created = datetime.fromtimestamp(a["created_date"], timezone.utc).date() if a["created_date"] else None
        r = dict(a)
        r.update({
            "code": code, "variant_id": m.get("variant_id"), "note": m.get("note") or "",
            "age_days": (t - created).days if created else None,
            "first_day": first.get(aid, {}).get("first_day"), "last_spend": first.get(aid, {}).get("last_spend"),
            "cps": _ratio(a["spent_budget"] or 0, a["actions"] or 0),
            "ctr": _ratio(a["clicks"] or 0, a["views"] or 0),
            "start_rate": _ratio(a["actions"] or 0, a["clicks"] or 0),
            "purchases": cv.get("purchases", 0), "revenue": cv.get("revenue", 0),
            "cpp": _ratio(a["spent_budget"] or 0, cv.get("purchases", 0)) if cv.get("purchases") else None,
            "running": a["status"] == "active" and not a["is_paused"],
        })
        for key, w in (("7", w7), ("28", w28), ("since", ws)):
            x = w.get(aid, {"views": 0, "clicks": 0, "starts": 0, "spent": 0.0})
            r[f"spent_{key}"] = x["spent"]
            r[f"starts_{key}"] = x["starts"]
            r[f"clicks_{key}"] = x["clicks"]
            r[f"views_{key}"] = x["views"]
            r[f"cps_{key}"] = _ratio(x["spent"], x["starts"])
        out.append(r)
    return out


def early_cps(ad_id, first_day, days=14):
    if not first_day:
        return None
    end = (date.fromisoformat(first_day) + timedelta(days=days - 1)).isoformat()
    r = db.one("SELECT SUM(spent) s, SUM(actions) a FROM stats WHERE ad_id=? AND day>=? AND day<=?", (ad_id, first_day, end))
    return _ratio(r["s"] or 0, r["a"] or 0) if r else None


def daily_totals(days=60):
    since = (today() - timedelta(days=days - 1)).isoformat()
    rows = db.query("""SELECT day, SUM(views) v, SUM(clicks) c, SUM(actions) a, SUM(spent) s
                       FROM stats WHERE day >= ? GROUP BY day ORDER BY day""", (since,))
    have = {r["day"]: r for r in rows}
    out = []
    for i in range(days):
        d = (today() - timedelta(days=days - 1 - i)).isoformat()
        r = have.get(d, {})
        out.append({"day": d, "views": r.get("v") or 0, "clicks": r.get("c") or 0, "starts": r.get("a") or 0,
                    "spent": round(r.get("s") or 0, 5)})
    return out


def ad_daily(ad_id):
    rows = db.query("SELECT day, views, clicks, actions AS starts, spent FROM stats WHERE ad_id=? ORDER BY day", (ad_id,))
    if not rows:
        return []
    have = {r["day"]: r for r in rows}
    d, end, out = date.fromisoformat(rows[0]["day"]), today(), []
    while d <= end:
        k = d.isoformat()
        out.append(have.get(k) or {"day": k, "views": 0, "clicks": 0, "starts": 0, "spent": 0})
        d += timedelta(days=1)
    return out


def summary():
    t = today()
    out = {}
    for key, days in (("7", 7), ("28", 28)):
        since = (t - timedelta(days=days - 1)).isoformat()
        prev_since = (t - timedelta(days=2 * days - 1)).isoformat()
        prev_until = (t - timedelta(days=days)).isoformat()
        cur = db.one("SELECT SUM(views) v, SUM(clicks) c, SUM(actions) a, SUM(spent) s FROM stats WHERE day>=?", (since,))
        prv = db.one("SELECT SUM(spent) s, SUM(actions) a FROM stats WHERE day>=? AND day<=?", (prev_since, prev_until))
        s, a = cur["s"] or 0, cur["a"] or 0
        ps, pa = prv["s"] or 0, prv["a"] or 0
        out[key] = {"spent": s, "starts": a, "clicks": cur["c"] or 0, "views": cur["v"] or 0,
                    "cps": _ratio(s, a), "prev_cps": _ratio(ps, pa), "prev_spent": ps}
    conv = db.one("""SELECT SUM(CASE WHEN event='purchase' THEN 1 ELSE 0 END) p FROM conversions
                     WHERE ts >= ?""", (db.now() - 28 * 86400,))
    out["purchases_28"] = (conv or {}).get("p") or 0
    out["account"] = db.one("SELECT * FROM account WHERE id=1") or {}
    counts = db.one("""SELECT SUM(CASE WHEN status='active' AND is_paused=0 THEN 1 ELSE 0 END) running,
                       SUM(CASE WHEN status IN ('in_review','ready_for_review') THEN 1 ELSE 0 END) review,
                       SUM(CASE WHEN status='declined' THEN 1 ELSE 0 END) declined FROM ads WHERE gone=0""")
    out["counts"] = counts or {}
    return out
