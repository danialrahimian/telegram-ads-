"""Turns the numbers into proposals. Nothing here touches Telegram: a person approves first."""
import json

from . import db, metrics

KIND_LABEL = {
    "withdraw": "پس گرفتن بودجه (دیگر نمایش داده نمی‌شود)",
    "stop": "توقف و پس گرفتن بودجه (پرهزینه)",
    "refresh": "تازه کردن متن (خستگی آگهی)",
    "topup": "شارژ آگهی خوب",
}


def _fmt(x, p=3):
    return "—" if x is None else f"{x:.{p}f}"


def evaluate(r, s):
    """Return (kind, amount, reason) or None for one ad row from metrics.ad_rows()."""
    if not r["running"]:
        return None
    remaining = r["remaining_budget"] or 0
    has_budget = remaining > 0.01
    age = r["age_days"] or 0
    target = s["target_cost_per_customer"]

    # 1. Stalled: still has budget but Telegram no longer shows it.
    if has_budget and age >= s["stalled_min_age_days"] and remaining > s["stalled_min_remaining"] and r["spent_28"] < s["stalled_spend_28d"]:
        return ("withdraw", remaining,
                f"در ۲۸ روز اخیر فقط {_fmt(r['spent_28'])} TON خرج کرده ولی {_fmt(remaining)} TON بودجه روی آن مانده.")

    # 2. Expensive. Real purchases win over bot starts when there are enough of them.
    if not has_budget:
        pass  # an empty ad stops by itself; only a top-up could apply
    elif r["purchases"] >= s["min_purchases_to_judge"] and r["cpp"] is not None:
        if r["cpp"] > target:
            return ("stop", remaining,
                    f"هر مشتری {_fmt(r['cpp'])} TON تمام شده؛ بیشتر از هدف {_fmt(target, 2)}.")
    elif r["spent_28"] >= s["min_spend_to_judge"]:
        if r["starts_28"] == 0 or (r["cps_28"] or 0) > s["stop_cost_per_start"]:
            return ("stop", remaining,
                    f"در ۲۸ روز اخیر هر استارت {_fmt(r['cps_28'])} TON؛ سقف {_fmt(s['stop_cost_per_start'])} است.")
    elif (r["spent_budget"] or 0) >= 2 * s["min_spend_to_judge"] and \
            (r["cps"] is None or r["cps"] > s["stop_cost_per_start"]) and \
            (r["cps_28"] is None or r["cps_28"] > s["stop_cost_per_start"]):
        # Slow spenders never reach the 28-day minimum; judge them on their whole life instead.
        return ("stop", remaining,
                f"کند خرج می‌کند و در کل عمرش هر استارت {_fmt(r['cps'])} TON بوده؛ سقف {_fmt(s['stop_cost_per_start'])} است.")

    # 3. Fatigue: same text getting expensive after a few weeks.
    if age >= s["fatigue_age_days"] and r["spent_7"] >= 0.2 and r["cps_7"]:
        early = metrics.early_cps(r["ad_id"], r["first_day"])
        if early and r["cps_7"] > s["fatigue_ratio"] * early:
            return ("refresh", 0,
                    f"هزینه هر استارت در ۷ روز اخیر {_fmt(r['cps_7'])} است در برابر {_fmt(early)} در دو هفته‌ی اول.")

    # 4. Winner about to run out: top up.
    good = (r["cps_28"] is not None and r["cps_28"] <= s["scale_cost_per_start"])
    if r["purchases"] >= s["min_purchases_to_judge"] and r["cpp"] is not None:
        good = r["cpp"] <= 0.6 * target
    if good and r["spent_28"] >= s["min_spend_to_judge"] and remaining < 2 * r["spent_28"]:
        amount = min(max(2 * r["spent_28"] - remaining, 0.2), s["topup_max_per_ad"])
        amount = round(amount, 2)
        return ("topup", amount,
                f"هر استارت {_fmt(r['cps_28'])} TON در ۲۸ روز اخیر؛ بودجه‌ی مانده ({_fmt(remaining)}) کمتر از دو برابر خرج ماهانه است.")
    return None


def generate():
    s = db.settings()
    if s.get("automation_paused"):
        return {"created": 0, "updated": 0, "expired": 0, "paused": True}
    busy = {r["ad_id"] for r in db.query("SELECT DISTINCT ad_id FROM jobs WHERE status IN ('queued','running')")}
    pending = {(r["ad_id"], r["kind"]): r for r in db.query("SELECT * FROM proposals WHERE status='pending'")}
    snoozed = {(r["ad_id"], r["kind"]) for r in db.query(
        "SELECT ad_id, kind FROM proposals WHERE status='rejected' AND decided_at >= ?", (db.now() - 7 * 86400,))}
    keep = set()
    created = updated = 0
    for r in metrics.ad_rows():
        if r["ad_id"] in busy:
            keep.update(k for k in pending if k[0] == r["ad_id"])
            continue
        res = evaluate(r, s)
        if not res:
            continue
        kind, amount, reason = res
        key = (r["ad_id"], kind)
        if key in snoozed:  # the user said no recently; ask again after a week
            continue
        keep.add(key)
        snap = json.dumps({k: r.get(k) for k in ("spent_28", "starts_28", "cps_28", "spent_7", "cps_7", "remaining_budget",
                                                  "age_days", "purchases", "cpp", "target_label")}, ensure_ascii=False)
        with db.tx() as t:
            if key in pending:
                t.execute("UPDATE proposals SET amount=?, reason=?, metrics=? WHERE id=?",
                          (amount, reason, snap, pending[key]["id"]))
                updated += 1
            else:
                t.execute("INSERT INTO proposals(created_at, ad_id, kind, amount, reason, metrics) VALUES (?,?,?,?,?,?)",
                          (db.now(), r["ad_id"], kind, amount, reason, snap))
                created += 1
    expired = 0
    with db.tx() as t:
        for key, p in pending.items():
            if key not in keep:
                t.execute("UPDATE proposals SET status='expired', decided_at=?, result=? WHERE id=?",
                          (db.now(), "شرایط دیگر برقرار نیست", p["id"]))
                expired += 1
    if created:
        db.log("rules", "proposals", None, f"{created} پیشنهاد جدید")
    return {"created": created, "updated": updated, "expired": expired, "paused": False}
