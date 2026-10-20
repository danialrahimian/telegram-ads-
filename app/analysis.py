"""Purchase tracking, the export bundle for Claude, and the optional direct Claude API call."""
import csv
import io
import json
import zipfile
from datetime import datetime, timezone

import httpx

from . import config, db, metrics

EVENTS = ("start", "purchase")


def parse_ts(ts):
    """Unix seconds, or an ISO date/time; anything else means now."""
    if ts in (None, ""):
        return db.now()
    try:
        return int(float(ts))
    except (TypeError, ValueError):
        pass
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return int(d.timestamp())
    except ValueError:
        return db.now()


def record_conversions(items, source="api"):
    """items: list of {code, event, amount?, id?, ts?}. Returns (added, skipped, errors)."""
    added = skipped = 0
    errors = []
    with db.tx() as t:
        for i, it in enumerate(items):
            if not isinstance(it, dict):
                errors.append(f"ردیف {i + 1}: باید یک شیء JSON باشد")
                continue
            code = str(it.get("code") or "").strip()
            event = str(it.get("event") or "purchase").strip().lower()
            if not code or event not in EVENTS:
                errors.append(f"ردیف {i + 1}: code یا event نامعتبر")
                continue
            try:
                amount = float(it["amount"]) if it.get("amount") not in (None, "") else None
            except (TypeError, ValueError):
                errors.append(f"ردیف {i + 1}: amount عدد نیست")
                continue
            ext = str(it.get("id")) if it.get("id") not in (None, "") else None
            ts = parse_ts(it.get("ts"))
            cur = t.execute("INSERT OR IGNORE INTO conversions(code, event, amount, ext_id, ts) VALUES (?,?,?,?,?)",
                            (code, event, amount, ext, ts))
            if cur.rowcount:
                added += 1
            else:
                skipped += 1
    if added:
        db.log(source, "conversions", None, f"{added} رویداد ثبت شد")
    return added, skipped, errors


def parse_csv(text):
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    return [{k.strip().lower(): (v or "").strip() for k, v in row.items() if k} for row in reader]


def by_code():
    rows = db.query("""SELECT m.code, m.ad_id, a.target_label, a.spent_budget, a.actions,
                       SUM(CASE WHEN c.event='purchase' THEN 1 ELSE 0 END) purchases,
                       SUM(CASE WHEN c.event='purchase' THEN COALESCE(c.amount,0) ELSE 0 END) revenue,
                       SUM(CASE WHEN c.event='start' THEN 1 ELSE 0 END) bot_starts
                       FROM ad_meta m LEFT JOIN ads a ON a.ad_id=m.ad_id LEFT JOIN conversions c ON c.code=m.code
                       WHERE m.code IS NOT NULL AND m.code != '' GROUP BY m.code ORDER BY purchases DESC""")
    for r in rows:
        r["cpp"] = (r["spent_budget"] / r["purchases"]) if r["purchases"] else None
        r["buy_rate"] = (r["purchases"] / r["actions"]) if r["actions"] else None
    orphan = db.query("""SELECT code, COUNT(*) n FROM conversions WHERE code NOT IN
                         (SELECT code FROM ad_meta WHERE code IS NOT NULL) GROUP BY code ORDER BY n DESC LIMIT 50""")
    return rows, orphan


def variant_performance():
    rows = db.query("""SELECT v.id, v.name, v.text, v.active, COUNT(m.ad_id) ads,
                       SUM(a.views) views, SUM(a.clicks) clicks, SUM(a.actions) starts, SUM(a.spent_budget) spent
                       FROM variants v LEFT JOIN ad_meta m ON m.variant_id=v.id LEFT JOIN ads a ON a.ad_id=m.ad_id
                       GROUP BY v.id ORDER BY v.id""")
    conv = metrics.conversions_by_code()
    codes = {}
    for r in db.query("SELECT variant_id, code FROM ad_meta WHERE variant_id IS NOT NULL"):
        codes.setdefault(r["variant_id"], []).append(r["code"])
    for r in rows:
        r["purchases"] = sum(conv.get(c, {}).get("purchases", 0) for c in codes.get(r["id"], []))
        r["cps"] = (r["spent"] / r["starts"]) if r["starts"] else None
        r["ctr"] = (r["clicks"] / r["views"]) if r["views"] else None
        r["cpp"] = (r["spent"] / r["purchases"]) if r["purchases"] else None
    return rows


def summary_for_claude():
    s = db.settings()
    rows = metrics.ad_rows()
    keep = [r for r in rows if r["running"] or r["spent_28"] > 0]
    keep.sort(key=lambda r: -(r["spent_28"] or 0))
    fields = ("ad_id", "target_label", "placement", "status", "cpm", "age_days", "remaining_budget", "spent_budget",
              "actions", "cps", "spent_28", "starts_28", "cps_28", "spent_7", "cps_7", "code", "purchases", "cpp", "text")
    return {
        "currency": (db.one("SELECT currency FROM account WHERE id=1") or {}).get("currency"),
        "today": metrics.today().isoformat(),
        "account": db.one("SELECT title, spent_budget, remaining_budget, ads_budget FROM account WHERE id=1"),
        "summary": {k: v for k, v in metrics.summary().items() if k in ("7", "28", "purchases_28", "counts")},
        "targets": {k: s[k] for k in ("target_cost_per_customer", "stop_cost_per_start", "scale_cost_per_start")},
        "ads": [{k: (round(r[k], 5) if isinstance(r[k], float) else r[k]) for k in fields} for r in keep[:80]],
        "variants": [{k: v for k, v in r.items()} for r in variant_performance()],
        "pending_proposals": db.query("SELECT ad_id, kind, amount, reason FROM proposals WHERE status='pending'"),
        "daily_last_60": metrics.daily_totals(60),
    }


PROMPT = """این بسته خروجی برنامه‌ی مدیریت تبلیغات تلگرام سایکونت است (همه‌ی مبالغ به TON).
فایل‌ها: ads.csv (هر آگهی با معیارهای کل، ۷ و ۲۸ روز اخیر)، daily.csv (آمار روزانه‌ی هر آگهی)،
conversions.csv (رویدادهای استارت و خرید با کد ردیابی)، summary.json (خلاصه، هدف‌ها و پیشنهادهای در انتظار).
هدف: هزینه‌ی هر مشتری کمتر از {target} TON.
لطفاً: ۱) عملکرد ۲۸ روز اخیر را با قبلش مقایسه کن، ۲) بهترین و بدترین جایگاه‌ها و متن‌ها را بگو،
۳) پیشنهادهای در انتظار را بررسی کن و بگو کدام را تأیید کنم، ۴) برنامه‌ی قدم‌به‌قدم هفته‌ی آینده را بده."""


def export_zip():
    buf = io.BytesIO()
    rows = metrics.ad_rows()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        def write_csv(name, data, cols):
            sio = io.StringIO()
            w = csv.DictWriter(sio, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in data:
                w.writerow(r)
            z.writestr(name, "﻿" + sio.getvalue())
        write_csv("ads.csv", rows, ["ad_id", "title", "status", "is_paused", "placement", "target_label", "cpm", "age_days",
                                    "views", "clicks", "actions", "spent_budget", "remaining_budget", "cps", "views_28",
                                    "clicks_28", "starts_28", "spent_28", "cps_28", "spent_7", "cps_7", "code",
                                    "purchases", "cpp", "last_spend", "text"])
        write_csv("daily.csv", db.query("SELECT ad_id, day, views, clicks, actions, spent FROM stats ORDER BY day, ad_id"),
                  ["ad_id", "day", "views", "clicks", "actions", "spent"])
        write_csv("conversions.csv", db.query("SELECT code, event, amount, ts FROM conversions ORDER BY ts"),
                  ["code", "event", "amount", "ts"])
        z.writestr("summary.json", json.dumps(summary_for_claude(), ensure_ascii=False, indent=1, default=str))
        z.writestr("PROMPT.txt", PROMPT.format(target=db.settings()["target_cost_per_customer"]))
    return buf.getvalue()


SYSTEM = ("تو تحلیلگر تبلیغات تلگرام برای برند فروش VPN «سایکونت» هستی. با داده‌ی داده‌شده دقیق و عددی تحلیل کن، "
          "به فارسی و با فهرست‌های کوتاه جواب بده، و هر توصیه را به عدد مشخصی از داده وصل کن. "
          "«استارت» یعنی شروع ربات، نه خرید. اگر داده برای نتیجه‌ای کافی نیست، صریح بگو.")


def ask_claude(question):
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("کلید Claude API در فایل .env تنظیم نشده است.")
    data = json.dumps(summary_for_claude(), ensure_ascii=False, default=str)
    body = {
        "model": config.ANTHROPIC_MODEL, "max_tokens": 4000, "system": SYSTEM,
        "messages": [{"role": "user", "content": f"{question}\n\nداده‌ها (JSON):\n{data}"}],
    }
    resp = httpx.post("https://api.anthropic.com/v1/messages", json=body, timeout=180,
                      headers={"x-api-key": config.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"})
    if resp.status_code != 200:
        raise RuntimeError(f"Claude API: HTTP {resp.status_code} {resp.text[:300]}")
    out = "".join(b.get("text", "") for b in resp.json().get("content", []) if b.get("type") == "text")
    with db.tx() as t:
        t.execute("INSERT INTO analyses(ts, model, question, output) VALUES (?,?,?,?)",
                  (db.now(), config.ANTHROPIC_MODEL, question, out))
    db.log("user", "claude_analysis", None, question[:100])
    return out
