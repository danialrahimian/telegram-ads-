"""Rules that turn an account's numbers into proposals. Nothing here touches Telegram."""

from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import now_ts
from app.db.session import session_scope
from app.models import Account, BulkItem, BulkOperation, Job, Proposal
from app.services import budget, events, guidelines, metrics
from app.services.accounts import settings_of

KIND_LABEL = {
    "withdraw": "پس گرفتن بودجه (دیگر نمایش داده نمی‌شود)",
    "stop": "توقف و پس گرفتن بودجه (پرهزینه)",
    "refresh": "تازه کردن متن (خستگی آگهی)",
    "topup": "شارژ آگهی خوب",
    "refill": "شارژ دوباره‌ی آگهی خوبِ بی‌بودجه",
    "replace": "جایگزینی آگهی (مشکل متن یا عکس)",
}
SNOOZE_SECONDS = 7 * 86400


def _fmt(x: float | None, p: int = 3) -> str:
    return "—" if x is None else f"{x:.{p}f}"


def _days(x: float) -> str:
    return f"{x:.0f}" if x >= 1 else f"{x:.1f}"


def _is_good(r: dict[str, Any], st: dict[str, Any]) -> bool:
    """Good on the days it had budget: cheap starts, or cheap customers when there are enough buyers."""
    if (r["buyers"] or 0) >= st["min_purchases_to_judge"] and r["cpp"] is not None:
        return bool(r["cpp"] <= 0.6 * st["target_cost_per_customer"])
    return r["cps_f28"] is not None and r["cps_f28"] <= st["scale_cost_per_start"]


def _replace(r: dict[str, Any], st: dict[str, Any]) -> tuple[str, float, str] | None:
    if r["status"] == "declined" or r.get("decline_reason"):
        why = r.get("decline_reason") or "دلیلی اعلام نشده"
        return ("replace", 0, f"تلگرام این آگهی را رد کرده است: «{why}». با متن یا عکس منطبق با قوانین جایگزینش کنید.")
    return None


def evaluate(r: dict[str, Any], st: dict[str, Any], early: float | None) -> tuple[str, float, str] | None:
    """Return (kind, amount, reason) for one ad row from metrics.ad_rows(), or None.

    Spend-based rules look only at days the ad had budget (see services/budget.py): an ad that sat
    without money is not "stalled" and its cost per start is measured on its last 28 funded days.
    """
    if r.get("archived"):
        return None
    declined = _replace(r, st)
    if declined:
        return declined
    if not r.get("has_stats"):
        return None  # judge an ad only once its daily stats have been fetched
    remaining = r["remaining"] or 0
    has_budget = remaining > budget.EMPTY
    target = st["target_cost_per_customer"]

    # 0. A good ad that ran out of budget: propose a refill (only ads not stopped on purpose).
    if (
        not has_budget
        and not r["is_paused"]
        and r["status"] in ("active", "on_hold")
        and r.get("empty_days") is not None
        and r["empty_days"] <= st["refill_max_empty_days"]
        and r["spent_f28"] >= st["min_spend_to_judge"]
        and _is_good(r, st)
    ):
        monthly = r["spent_f28"] * 28 / max(r["funded_days_28"], 1)
        amount = round(min(max(2 * monthly, 0.2), st["topup_max_per_ad"]), 2)
        days = r["empty_days"]
        how = (
            f"هر مشتری {_fmt(r['cpp'])}"
            if (r["buyers"] or 0) >= st["min_purchases_to_judge"] and r["cpp"] is not None
            else f"هر استارت {_fmt(r['cps_f28'])}"
        )
        return (
            "refill",
            amount,
            ("از امروز بودجه ندارد. " if days == 0 else f"{days} روز است بودجه ندارد. ")
            + f"در {r['funded_days_28']} روزی که بودجه داشت {how} بود و ماهانه حدود {_fmt(monthly)} خرج می‌کرد.",
        )

    if not r["running"]:
        return None

    # 1. Stalled: holds budget, has had it for a while without a break, and barely spends in that time.
    window = r.get("window_days") or 0
    allowed = st["stalled_spend_28d"] * min(window, 28) / 28
    if (
        has_budget
        and window >= st["stalled_min_age_days"]
        and remaining > st["stalled_min_remaining"]
        and r["spent_window"] < allowed
    ):
        return (
            "withdraw",
            remaining,
            f"در {_days(window)} روز اخیر که پیوسته بودجه داشته فقط {_fmt(r['spent_window'])} خرج کرده "
            f"(کمتر از {_fmt(allowed)}) ولی {_fmt(remaining)} بودجه روی آن مانده.",
        )

    # 2. No views for days while the account's other ads are shown: the ad itself is the problem.
    zero = r.get("zero_view_days") or 0
    if has_budget and zero >= st["replace_zero_view_days"] and (r.get("others_views_in_streak") or 0) > 0:
        return (
            "replace",
            0,
            f"{zero} روز پیاپی با وجود بودجه هیچ نمایشی نگرفته، در حالی که آگهی‌های دیگر حساب در همین مدت "
            f"{r['others_views_in_streak']} نمایش داشته‌اند؛ احتمالاً مشکل از متن یا عکس خود آگهی است.",
        )

    # 3. Expensive. Real buyers (from the sales bot) win over bot starts when there are enough of them.
    if has_budget:
        if (r["buyers"] or 0) >= st["min_purchases_to_judge"] and r["cpp"] is not None:
            if r["cpp"] > target:
                return ("stop", remaining, f"هر مشتری {_fmt(r['cpp'])} تمام شده؛ بیشتر از هدف {_fmt(target, 2)}.")
        elif r["spent_f28"] >= st["min_spend_to_judge"]:
            if r["starts_f28"] == 0 or (r["cps_f28"] or 0) > st["stop_cost_per_start"]:
                return (
                    "stop",
                    remaining,
                    f"در {r['funded_days_28']} روز اخیرِ دارای بودجه هر استارت {_fmt(r['cps_f28'])}؛ "
                    f"سقف {_fmt(st['stop_cost_per_start'])} است.",
                )
        elif (
            (r["spent"] or 0) >= 2 * st["min_spend_to_judge"]
            and (r["cps"] is None or r["cps"] > st["stop_cost_per_start"])
            and (r["cps_f28"] is None or r["cps_f28"] > st["stop_cost_per_start"])
        ):
            return (
                "stop",
                remaining,
                f"کند خرج می‌کند و در کل عمرش هر استارت {_fmt(r['cps'])} بوده؛ سقف {_fmt(st['stop_cost_per_start'])}.",
            )

    # 4. A text that probably breaks Telegram's ad guidelines (invented urgency, emoji, links...).
    check = guidelines.check(r.get("text") or "", promote_url=r.get("promote_url"))
    if check["likely_violation"]:
        return (
            "replace",
            0,
            "متن آگهی احتمالاً با قوانین تبلیغات تلگرام نمی‌خواند: " + guidelines.summary(check),
        )

    # 5. Fatigue: the same text getting expensive after a few weeks.
    age = r["age_days"] or 0
    if (
        age >= st["fatigue_age_days"]
        and r["spent_7"] >= 0.2
        and r["cps_7"]
        and early
        and r["cps_7"] > st["fatigue_ratio"] * early
    ):
        return (
            "refresh",
            0,
            f"هزینه هر استارت در ۷ روز اخیر {_fmt(r['cps_7'])} است در برابر {_fmt(early)} در دو هفته‌ی اول.",
        )

    # 6. A winner about to run out: top up.
    monthly = r["spent_f28"] * 28 / max(r["funded_days_28"], 1)
    if _is_good(r, st) and r["spent_f28"] >= st["min_spend_to_judge"] and remaining < 2 * monthly:
        amount = round(min(max(2 * monthly - remaining, 0.2), st["topup_max_per_ad"]), 2)
        return (
            "topup",
            amount,
            f"هر استارت {_fmt(r['cps_f28'])} در {r['funded_days_28']} روز اخیرِ دارای بودجه؛ "
            f"بودجه‌ی مانده ({_fmt(remaining)}) کمتر از دو برابر خرج ماهانه است.",
        )
    return None


async def _generate(s: AsyncSession, acc: Account) -> dict[str, Any]:
    st = settings_of(acc)
    if acc.automation_paused:
        return {"created": 0, "updated": 0, "expired": 0, "paused": True}
    now = now_ts()
    busy = {
        int(x)
        for x in (
            await s.execute(select(Job.ad_id).where(Job.account_id == acc.id, Job.status.in_(("queued", "running"))))
        ).scalars()
    }
    pending = {
        (p.ad_id, p.kind): p
        for p in (
            await s.execute(select(Proposal).where(Proposal.account_id == acc.id, Proposal.status == "pending"))
        ).scalars()
    }
    snoozed = {
        (p.ad_id, p.kind)
        for p in (
            await s.execute(
                select(Proposal).where(
                    Proposal.account_id == acc.id,
                    Proposal.status == "rejected",
                    Proposal.decided_ts >= now - SNOOZE_SECONDS,
                )
            )
        ).scalars()
    }
    keep: set[tuple[int, str]] = set()
    created = updated = 0
    for old, new in await s.execute(
        select(BulkItem.ad_id, BulkItem.new_ad_id)
        .join(BulkOperation, BulkOperation.id == BulkItem.op_id)
        .where(
            BulkItem.account_id == acc.id,
            BulkOperation.status == "running",
            or_(
                BulkItem.status.in_(("pending", "submitted", "in_review")),
                and_(BulkItem.status == "approved", BulkItem.step != "done"),
            ),
        )
    ):
        busy.add(int(old))
        if new:
            busy.add(int(new))
    for r in await metrics.ad_rows(s, acc):
        if r["ad_id"] in busy:
            keep.update(k for k in pending if k[0] == r["ad_id"])
            continue
        early = None
        if r["running"] and (r["age_days"] or 0) >= st["fatigue_age_days"]:
            early = await metrics.early_cps(s, acc.id, r["ad_id"], r["first_day"])
        res = evaluate(r, st, early)
        if not res:
            continue
        kind, amount, reason = res
        key = (r["ad_id"], kind)
        if key in snoozed:
            continue
        keep.add(key)
        snap = {
            k: r.get(k)
            for k in (
                "spent_28",
                "starts_28",
                "cps_28",
                "spent_f28",
                "starts_f28",
                "cps_f28",
                "funded_days_28",
                "window_days",
                "spent_window",
                "empty_days",
                "zero_view_days",
                "decline_reason",
                "spent_7",
                "cps_7",
                "remaining",
                "age_days",
                "buyers",
                "cpp",
                "target_label",
            )
        }
        if key in pending:
            p = pending[key]
            p.amount, p.reason, p.metrics = amount, reason, snap
            updated += 1
        else:
            s.add(
                Proposal(
                    account_id=acc.id,
                    created_ts=now,
                    ad_id=r["ad_id"],
                    kind=kind,
                    amount=amount,
                    reason=reason,
                    metrics=snap,
                )
            )
            created += 1
    expired = 0
    for key, p in pending.items():
        if key not in keep:
            p.status, p.decided_ts, p.result = "expired", now, "شرایط دیگر برقرار نیست"
            expired += 1
    if created:
        events.log(s, "proposals", account_id=acc.id, actor="rules", detail=f"{created} پیشنهاد جدید")
    return {"created": created, "updated": updated, "expired": expired, "paused": False}


async def generate(account_id: int) -> dict[str, Any]:
    async with session_scope() as s:
        acc = await s.get(Account, account_id)
        if acc is None:
            return {"created": 0, "updated": 0, "expired": 0, "paused": False}
        return await _generate(s, acc)
