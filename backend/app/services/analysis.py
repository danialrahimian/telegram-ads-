"""Account-level analysis with Claude, and a data bundle to analyse elsewhere."""

import csv
import io
import json
import zipfile
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.integrations.anthropic import ClaudeClient, ClaudeError
from app.models import Account, AdStat, AiAnalysis, BotTransaction, Proposal
from app.services import app_settings, events, metrics, texts
from app.services.accounts import settings_of

SYSTEM = (
    "تو تحلیلگر تبلیغات تلگرام برای یک ربات فروش هستی. با داده‌ی داده‌شده دقیق و عددی تحلیل کن، "
    "به فارسی و با فهرست‌های کوتاه و تیتر جواب بده، و هر توصیه را به عدد مشخصی از داده وصل کن. "
    "«استارت» یعنی شروع ربات از لینک آگهی، نه خرید. «مشتری» کاربری است که از لینک یک برچسب معرف آمده و خرید کرده. "
    "اگر داده برای نتیجه‌ای کافی نیست، صریح بگو. خروجی Markdown ساده باشد."
)

DEFAULT_QUESTION = "عملکرد ۲۸ روز اخیر را تحلیل کن و قدم‌به‌قدم بگو این هفته چه کار کنم."


async def context(s: AsyncSession, acc: Account) -> dict[str, Any]:
    rows = await metrics.ad_rows(s, acc)
    keep = sorted([r for r in rows if r["running"] or r["spent_28"] > 0], key=lambda r: -(r["spent_28"] or 0))
    fields = (
        "ad_id",
        "target_label",
        "placement",
        "status",
        "cpm",
        "age_days",
        "remaining",
        "spent",
        "starts",
        "cps",
        "spent_28",
        "starts_28",
        "cps_28",
        "spent_7",
        "cps_7",
        "tag_name",
        "buyers",
        "cpp",
        "text",
    )
    perf = await texts.performance(s, acc)
    st = settings_of(acc)
    return {
        "account": {
            "name": acc.name,
            "currency": acc.currency,
            "bot": acc.bot_username,
            "balance": acc.remaining_budget,
            "on_ads": acc.ads_budget,
        },
        "targets": {k: st[k] for k in ("target_cost_per_customer", "stop_cost_per_start", "scale_cost_per_start")},
        "summary": await metrics.summary(s, acc),
        "ads": [{k: (round(r[k], 5) if isinstance(r[k], float) else r[k]) for k in fields} for r in keep[:80]],
        "referral_tags": await metrics.tag_rows(s, acc),
        "texts": [{"id": vid, **p} for vid, p in perf.items() if p.get("ads")],
        "pending_proposals": [
            {"ad_id": p.ad_id, "kind": p.kind, "amount": p.amount, "reason": p.reason}
            for p in (
                await s.execute(select(Proposal).where(Proposal.account_id == acc.id, Proposal.status == "pending"))
            ).scalars()
        ],
        "daily_last_60": await metrics.daily(s, acc, 60),
    }


async def ask(s: AsyncSession, acc: Account, question: str) -> AiAnalysis:
    q = (question or "").strip()[:2000] or DEFAULT_QUESTION
    key = await app_settings.claude_key(s)
    model = str(await app_settings.get(s, "claude_model"))
    data = json.dumps(await context(s, acc), ensure_ascii=False, default=str)
    try:
        out = await ClaudeClient(key, model).complete(SYSTEM, f"{q}\n\nداده‌ها (JSON):\n{data}", max_tokens=4000)
    except ClaudeError as e:
        raise AppError(str(e), code="claude_error") from None
    row = AiAnalysis(account_id=acc.id, kind="account", model=model, question=q, output=out)
    s.add(row)
    events.log(s, "claude_analysis", account_id=acc.id, actor="user", detail=q[:120])
    return row


PROMPT = """این بسته خروجی «Telegram Ads Manager» برای حساب «{name}» است (مبالغ تبلیغات به {currency}، فروش ربات به تومان).
فایل‌ها: ads.csv (هر آگهی با معیارهای کل، ۷ و ۲۸ روز اخیر)، daily_ad_stats.csv (آمار روزانه‌ی هر آگهی)،
bot_transactions.csv (دفتر تراکنش‌های ربات)، context.json (خلاصه، برچسب‌های معرف، متن‌ها و پیشنهادهای در انتظار).
هدف: هزینه‌ی هر مشتری کمتر از {target}.
لطفاً: ۱) عملکرد ۲۸ روز اخیر را با قبلش مقایسه کن، ۲) بهترین و بدترین جایگاه‌ها و متن‌ها را بگو،
۳) پیشنهادهای در انتظار را بررسی کن، ۴) برنامه‌ی قدم‌به‌قدم هفته‌ی آینده را بده."""


async def export_zip(s: AsyncSession, acc: Account) -> bytes:
    buf = io.BytesIO()
    rows = await metrics.ad_rows(s, acc)
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:

        def write_csv(name: str, data: list[dict[str, Any]], cols: list[str]) -> None:
            sio = io.StringIO()
            w = csv.DictWriter(sio, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(data)
            z.writestr(name, "﻿" + sio.getvalue())

        write_csv(
            "ads.csv",
            rows,
            [
                "ad_id",
                "title",
                "status",
                "is_paused",
                "placement",
                "target_label",
                "cpm",
                "age_days",
                "views",
                "clicks",
                "starts",
                "spent",
                "remaining",
                "cps",
                "spent_28",
                "starts_28",
                "cps_28",
                "spent_7",
                "cps_7",
                "tag_name",
                "buyers",
                "revenue",
                "cpp",
                "last_spend_day",
                "text",
            ],
        )
        stats = [
            {
                "ad_id": r.ad_id,
                "day": r.day,
                "views": r.views,
                "clicks": r.clicks,
                "actions": r.actions,
                "spent": r.spent,
            }
            for r in (
                await s.execute(select(AdStat).where(AdStat.account_id == acc.id).order_by(AdStat.day, AdStat.ad_id))
            ).scalars()
        ]
        write_csv("daily_ad_stats.csv", stats, ["ad_id", "day", "views", "clicks", "actions", "spent"])
        txs = [
            {
                "ext_id": t.ext_id,
                "user_id": t.user_id,
                "type": t.type,
                "source": t.source,
                "amount": t.amount,
                "created_ts": t.created_ts,
            }
            for t in (
                await s.execute(
                    select(BotTransaction)
                    .where(BotTransaction.account_id == acc.id)
                    .order_by(BotTransaction.created_ts)
                )
            ).scalars()
        ]
        write_csv("bot_transactions.csv", txs, ["ext_id", "user_id", "type", "source", "amount", "created_ts"])
        z.writestr("context.json", json.dumps(await context(s, acc), ensure_ascii=False, indent=1, default=str))
        z.writestr(
            "PROMPT.txt",
            PROMPT.format(
                name=acc.name, currency=acc.currency or "TON", target=settings_of(acc)["target_cost_per_customer"]
            ),
        )
    return buf.getvalue()
