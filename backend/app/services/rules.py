"""Rules that turn an account's numbers into proposals. Nothing here touches Telegram."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import now_ts
from app.db.session import session_scope
from app.models import Account, Job, Proposal
from app.services import events, metrics
from app.services.accounts import settings_of

KIND_LABEL = {
    "withdraw": "پس گرفتن بودجه (دیگر نمایش داده نمی‌شود)",
    "stop": "توقف و پس گرفتن بودجه (پرهزینه)",
    "refresh": "تازه کردن متن (خستگی آگهی)",
    "topup": "شارژ آگهی خوب",
}
SNOOZE_SECONDS = 7 * 86400


def _fmt(x: float | None, p: int = 3) -> str:
    return "—" if x is None else f"{x:.{p}f}"


def evaluate(r: dict[str, Any], st: dict[str, Any], early: float | None) -> tuple[str, float, str] | None:
    """Return (kind, amount, reason) for one ad row from metrics.ad_rows(), or None."""
    if not r["running"] or not r.get("has_stats"):
        return None  # judge an ad only once its daily stats have been fetched
    remaining = r["remaining"] or 0
    has_budget = remaining > 0.01
    age = r["age_days"] or 0
    target = st["target_cost_per_customer"]

    # 1. Stalled: still holds budget but Telegram no longer shows it.
    if (
        has_budget
        and age >= st["stalled_min_age_days"]
        and remaining > st["stalled_min_remaining"]
        and r["spent_28"] < st["stalled_spend_28d"]
    ):
        return (
            "withdraw",
            remaining,
            f"در ۲۸ روز اخیر فقط {_fmt(r['spent_28'])} خرج کرده ولی {_fmt(remaining)} بودجه روی آن مانده.",
        )

    # 2. Expensive. Real buyers (from the sales bot) win over bot starts when there are enough of them.
    if has_budget:
        if (r["buyers"] or 0) >= st["min_purchases_to_judge"] and r["cpp"] is not None:
            if r["cpp"] > target:
                return ("stop", remaining, f"هر مشتری {_fmt(r['cpp'])} تمام شده؛ بیشتر از هدف {_fmt(target, 2)}.")
        elif r["spent_28"] >= st["min_spend_to_judge"]:
            if r["starts_28"] == 0 or (r["cps_28"] or 0) > st["stop_cost_per_start"]:
                return (
                    "stop",
                    remaining,
                    f"در ۲۸ روز اخیر هر استارت {_fmt(r['cps_28'])}؛ سقف {_fmt(st['stop_cost_per_start'])} است.",
                )
        elif (
            (r["spent"] or 0) >= 2 * st["min_spend_to_judge"]
            and (r["cps"] is None or r["cps"] > st["stop_cost_per_start"])
            and (r["cps_28"] is None or r["cps_28"] > st["stop_cost_per_start"])
        ):
            return (
                "stop",
                remaining,
                f"کند خرج می‌کند و در کل عمرش هر استارت {_fmt(r['cps'])} بوده؛ سقف {_fmt(st['stop_cost_per_start'])}.",
            )

    # 3. Fatigue: the same text getting expensive after a few weeks.
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

    # 4. A winner about to run out: top up.
    good = r["cps_28"] is not None and r["cps_28"] <= st["scale_cost_per_start"]
    if (r["buyers"] or 0) >= st["min_purchases_to_judge"] and r["cpp"] is not None:
        good = r["cpp"] <= 0.6 * target
    if good and r["spent_28"] >= st["min_spend_to_judge"] and remaining < 2 * r["spent_28"]:
        amount = round(min(max(2 * r["spent_28"] - remaining, 0.2), st["topup_max_per_ad"]), 2)
        return (
            "topup",
            amount,
            f"هر استارت {_fmt(r['cps_28'])} در ۲۸ روز اخیر؛ بودجه‌ی مانده ({_fmt(remaining)}) کمتر از دو برابر خرج ماهانه است.",
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
