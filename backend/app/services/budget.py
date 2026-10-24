"""Budget history of each ad: when it got money and when it ran dry.

Telegram only reports the current `remaining_budget`, so the history is built from what the panel
observes: every fast sync compares the new value with the stored one, and the job runner records the
top-ups and withdrawals it makes itself. The rules use it to judge ads only on the days they could
actually spend (an ad that had no budget for three weeks did not "stop being shown").
"""

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ad, AdBudgetEvent

EMPTY = 0.01  # at or below this an ad counts as having no budget
DAY = 86400


def has_budget(remaining: float | None) -> bool:
    return (remaining or 0) > EMPTY


def _event(s: AsyncSession, ad: Ad, ts: int, kind: str, amount: float, remaining: float, actor: str) -> None:
    s.add(
        AdBudgetEvent(
            account_id=ad.account_id,
            ad_id=ad.ad_id,
            ts=ts,
            kind=kind,
            amount=round(amount, 5),
            remaining=round(remaining, 5),
            actor=actor,
        )
    )


def first_seen(ad: Ad, remaining: float, ts: int) -> None:
    """An ad the panel has never seen: assume it has been funded since it was created (no history to go on)."""
    ad.remaining_budget = remaining
    if has_budget(remaining):
        ad.funded_since_ts = ad.created_date or ts
        ad.empty_since_ts = 0
    else:
        ad.funded_since_ts = 0
        ad.empty_since_ts = 0  # unknown; the last day with spend stands in for it


def observe(
    s: AsyncSession, ad: Ad, remaining: float, ts: int, *, actor: str = "sync", kind: str | None = None
) -> None:
    """Record the change from the stored remaining budget to `remaining` and update the funded markers.

    actor="sync": a value read from Telegram; an unexplained jump up is a top-up made on the Telegram site.
    actor="app": a change the panel made itself (kind "topup" or "withdraw").
    """
    old = ad.remaining_budget or 0
    new = remaining or 0
    ad.remaining_budget = new
    if abs(new - old) <= 1e-9:
        return
    who = "site" if actor == "sync" and new > old else actor
    if not has_budget(old) and has_budget(new):
        _event(s, ad, ts, "funded", new - old, new, who)
        ad.funded_since_ts, ad.empty_since_ts = ts, 0
    elif has_budget(old) and not has_budget(new):
        _event(s, ad, ts, "withdraw" if kind == "withdraw" else "empty", old - new, new, actor)
        ad.funded_since_ts, ad.empty_since_ts = 0, ts
    elif new - old > EMPTY:
        _event(s, ad, ts, "topup", new - old, new, who)
    elif kind == "withdraw" and old - new > EMPTY:
        _event(s, ad, ts, "withdraw", old - new, new, actor)
    if has_budget(new) and not ad.funded_since_ts:
        ad.funded_since_ts = ts


def _day(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).date().isoformat()


def funded_days(
    events: list[tuple[int, str, float]],
    *,
    remaining: float,
    created_ts: int,
    spend_days: list[str],
    today: date,
    lookback: int = 120,
) -> set[str]:
    """UTC days (ISO) within the lookback on which the ad had budget at least part of the day.

    `events` are (ts, kind, remaining_after) in any order. Walking back from today: the state now is
    known; each "funded" event means the ad was empty before it, each drop to empty means it had budget
    before it. Where the panel has no history (before the oldest event, or no events at all), an ad with
    budget counts as funded back to its creation, and an empty one as funded up to its last day with spend.
    """
    start = today - timedelta(days=lookback - 1)
    created_day = max(datetime.fromtimestamp(created_ts, UTC).date(), start) if created_ts else start
    out: set[str] = set()

    def fill(first: date, last: date) -> None:
        d = max(first, start)
        while d <= last:
            out.add(d.isoformat())
            d += timedelta(days=1)

    state = has_budget(remaining)
    cursor = today
    for ts, kind, rem_after in sorted(events, key=lambda e: e[0], reverse=True):
        ev_day = datetime.fromtimestamp(ts, UTC).date()
        if state:
            fill(ev_day, cursor)
        if kind == "funded":
            state = False
        elif not has_budget(rem_after):
            state = True
        cursor = ev_day
        if cursor < start:
            return out
    if state:
        fill(created_day, cursor)
    else:
        last = max((d for d in spend_days if d <= cursor.isoformat()), default=None)
        if last:
            fill(created_day, date.fromisoformat(last))
    return out


async def events_by_ad(s: AsyncSession, account_id: int, since_ts: int) -> dict[int, list[tuple[int, str, float]]]:
    out: dict[int, list[tuple[int, str, float]]] = defaultdict(list)
    rows = await s.execute(
        select(AdBudgetEvent.ad_id, AdBudgetEvent.ts, AdBudgetEvent.kind, AdBudgetEvent.remaining).where(
            AdBudgetEvent.account_id == account_id, AdBudgetEvent.ts >= since_ts
        )
    )
    for ad_id, ts, kind, rem in rows:
        out[int(ad_id)].append((int(ts), str(kind), float(rem or 0)))
    return out


async def history(s: AsyncSession, account_id: int, ad_id: int, limit: int = 50) -> list[dict[str, Any]]:
    rows = (
        await s.execute(
            select(AdBudgetEvent)
            .where(AdBudgetEvent.account_id == account_id, AdBudgetEvent.ad_id == ad_id)
            .order_by(AdBudgetEvent.ts.desc(), AdBudgetEvent.id.desc())
            .limit(limit)
        )
    ).scalars()
    return [{"ts": e.ts, "kind": e.kind, "amount": e.amount, "remaining": e.remaining, "actor": e.actor} for e in rows]
