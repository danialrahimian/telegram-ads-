"""Ad text library: manual editing and analysis/rewrites with Claude."""

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, NotFound
from app.db.base import utcnow
from app.integrations.anthropic import ClaudeClient, ClaudeError
from app.models import Account, Ad, AiAnalysis, TextVariant
from app.services import app_settings, events, guidelines, metrics
from app.services.accounts import settings_of


def _ratio(a: float, b: float) -> float | None:
    return round(a / b, 5) if b else None


async def performance(s: AsyncSession, acc: Account) -> dict[int, dict[str, Any]]:
    """Totals of the ads that use each text: linked by variant_id, or with exactly the same text."""
    variants = list((await s.execute(select(TextVariant).where(TextVariant.account_id == acc.id))).scalars())
    by_text = {v.text.strip(): v.id for v in variants}
    rows = await metrics.ad_rows(s, acc, archived=None)
    out: dict[int, dict[str, Any]] = {
        v.id: {"ads": 0, "views": 0, "clicks": 0, "starts": 0, "spent": 0.0, "buyers": 0, "running": 0}
        for v in variants
    }
    for r in rows:
        vid = r["variant_id"] or by_text.get((r["text"] or "").strip())
        if vid not in out:
            continue
        d = out[vid]
        d["ads"] += 1
        d["running"] += 1 if r["running"] else 0
        for k in ("views", "clicks", "starts", "spent"):
            d[k] += r[k] or 0
        d["buyers"] += r["buyers"] or 0
    for d in out.values():
        d["ctr"] = _ratio(d["clicks"], d["views"])
        d["start_rate"] = _ratio(d["starts"], d["clicks"])
        d["cps"] = _ratio(d["spent"], d["starts"])
        d["cpp"] = _ratio(d["spent"], d["buyers"])
    return out


def _score(v: Any) -> int | None:
    try:
        return max(0, min(100, round(float(v))))
    except (TypeError, ValueError):
        return None


def _validate(name: str, text: str) -> tuple[str, str]:
    name, text = (name or "").strip(), (text or "").strip()
    if not name:
        raise AppError("نام متن را وارد کنید.")
    if not text:
        raise AppError("متن را وارد کنید.")
    if len(text) > 160:
        raise AppError(f"متن {len(text)} کاراکتر است؛ سقف تلگرام ۱۶۰ کاراکتر است.")
    return name[:80], text


async def get(s: AsyncSession, acc: Account, vid: int) -> TextVariant:
    v = await s.get(TextVariant, vid)
    if v is None or v.account_id != acc.id:
        raise NotFound("این متن پیدا نشد.")
    return v


async def create(s: AsyncSession, acc: Account, name: str, text: str, source: str = "manual") -> TextVariant:
    name, text = _validate(name, text)
    v = TextVariant(account_id=acc.id, name=name, text=text, source=source)
    s.add(v)
    await s.flush()
    events.log(s, "text_created", account_id=acc.id, actor="user", detail=name)
    return v


async def update(
    s: AsyncSession, acc: Account, vid: int, *, name: str | None, text: str | None, active: bool | None
) -> TextVariant:
    v = await get(s, acc, vid)
    new_name, new_text = _validate(name if name is not None else v.name, text if text is not None else v.text)
    if new_text != v.text:
        used = (await s.execute(select(Ad.id).where(Ad.account_id == acc.id, Ad.variant_id == v.id).limit(1))).first()
        if used:
            # Keep the A/B numbers of the old wording: retire it and save the edit as a new text.
            v.active = False
            nv = TextVariant(account_id=acc.id, name=new_name, text=new_text, source="manual")
            s.add(nv)
            await s.flush()
            events.log(s, "text_versioned", account_id=acc.id, actor="user", detail=new_name)
            return nv
    v.name, v.text = new_name, new_text
    if active is not None:
        v.active = active
    v.updated_at = utcnow()
    return v


async def delete(s: AsyncSession, acc: Account, vid: int) -> None:
    v = await get(s, acc, vid)
    await s.delete(v)
    events.log(s, "text_deleted", account_id=acc.id, actor="user", detail=v.name)


async def import_from_ads(s: AsyncSession, acc: Account) -> int:
    existing = {
        v.text.strip() for v in (await s.execute(select(TextVariant).where(TextVariant.account_id == acc.id))).scalars()
    }
    texts = [
        t
        for (t,) in await s.execute(
            select(Ad.text).where(Ad.account_id == acc.id, Ad.gone.is_(False)).group_by(Ad.text)
        )
    ]
    n = 0
    for t in texts:
        t = (t or "").strip()
        if t and t not in existing and len(t) <= 160:
            n += 1
            s.add(TextVariant(account_id=acc.id, name=f"متن آگهی‌ها {n}", text=t, source="imported"))
            existing.add(t)
    return n


SYSTEM = """تو کپی‌رایتر و تحلیلگر تبلیغات تلگرام هستی. آگهی‌ها پست‌های اسپانسری تلگرام‌اند با سقف ۱۶۰ کاراکتر و یک دکمه که کاربر را به ربات فروش می‌برد.
خروجی فقط یک شیء JSON باشد، بدون هیچ متن دیگری، با این ساختار:
{"score": عدد ۰ تا ۱۰۰, "summary": "جمع‌بندی یک‌جمله‌ای",
 "strengths": ["..."],
 "issues": [{"issue": "...", "severity": "high|medium|low", "fix": "..."}],
 "rewrites": [{"text": "متن جدید زیر ۱۶۰ کاراکتر", "angle": "زاویه‌ی پیام در چند کلمه"}]}
قواعد: فارسی روان و طبیعی؛ دقیقاً ۳ بازنویسی؛ هر بازنویسی حداکثر ۱۶۰ کاراکتر با احتساب ایموجی؛ نام برند را حفظ کن؛
ادعای جدید یا قیمت جدید از خودت نساز؛ فوریت ساختگی ننویس؛ اگر عدد عملکرد داده شده، تحلیل را به آن عددها وصل کن."""


async def analyze(s: AsyncSession, acc: Account, vid: int, goal: str = "") -> dict[str, Any]:
    v = await get(s, acc, vid)
    perf = (await performance(s, acc)).get(v.id, {})
    key = await app_settings.claude_key(s)
    model = await app_settings.get(s, "claude_model")
    st = settings_of(acc)
    context = {
        "brand": acc.name,
        "bot": f"@{acc.bot_username}" if acc.bot_username else None,
        "currency": acc.currency or None,
        "text": v.text,
        "length": len(v.text),
        "performance_of_ads_using_this_text": perf if perf.get("ads") else "هنوز آگهی‌ای با این متن اجرا نشده",
        "account_targets": {
            "target_cost_per_customer": st["target_cost_per_customer"],
            "stop_cost_per_start": st["stop_cost_per_start"],
        },
        "user_goal": goal.strip() or None,
    }
    prompt = "این متن آگهی را تحلیل کن و سه بازنویسی بده.\n\n" + json.dumps(context, ensure_ascii=False, indent=1)
    try:
        result = await ClaudeClient(key, model).complete_json(SYSTEM, prompt, max_tokens=2000)
    except ClaudeError as e:
        raise AppError(str(e), code="claude_error") from None
    rewrites = []
    for r in result.get("rewrites") or []:
        if isinstance(r, dict) and isinstance(r.get("text"), str) and r["text"].strip():
            t = r["text"].strip()
            rewrites.append({"text": t, "angle": str(r.get("angle") or ""), "length": len(t), "too_long": len(t) > 160})
    analysis = {
        "score": _score(result.get("score")),
        "summary": str(result.get("summary") or ""),
        "strengths": [str(x) for x in result.get("strengths") or []][:8],
        "issues": [i for i in result.get("issues") or [] if isinstance(i, dict)][:10],
        "rewrites": rewrites[:5],
        "model": model,
    }
    v.analysis, v.analyzed_at = analysis, utcnow()
    s.add(
        AiAnalysis(
            account_id=acc.id,
            kind="text",
            target_id=v.id,
            model=str(model),
            question=goal[:500],
            output=json.dumps(analysis, ensure_ascii=False),
        )
    )
    events.log(s, "text_analyzed", account_id=acc.id, actor="user", detail=v.name)
    return analysis


def public(v: TextVariant, perf: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "id": v.id,
        "name": v.name,
        "text": v.text,
        "active": v.active,
        "source": v.source,
        "length": len(v.text),
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "updated_at": v.updated_at.isoformat() if v.updated_at else None,
        "analysis": v.analysis,
        "analyzed_at": v.analyzed_at.isoformat() if v.analyzed_at else None,
        "performance": perf or {},
    }


COMPLIANT_SYSTEM = """تو کپی‌رایتر تبلیغات تلگرام هستی و متن‌ها را با قوانین تبلیغات تلگرام (ads.telegram.org/guidelines) منطبق می‌کنی.
خروجی فقط یک شیء JSON باشد: {"text": "متن نهایی", "notes": ["چه چیزی عوض شد و چرا"]}.
قواعد متن: فارسی روان؛ حداکثر ۱۶۰ کاراکتر با احتساب ایموجی؛ یک پاراگراف بدون خط جدید و بدون فهرست؛ حداکثر یک ایموجی؛
بدون حروف یا علامت‌گذاری نمایشی (!!!، ★)؛ بدون فوریت ساختگی («تا آخر امشب»، «فقط امروز»، «آخرین فرصت»)؛ بدون ادعای گمراه‌کننده یا کلیک‌خور؛
بدون عبارت مبهم و تکراری؛ بدون لینک در متن مگر همان لینک آگهی؛ بدون کوتاه‌کننده‌ی لینک؛ نام برند را حفظ کن؛ قیمت یا ادعای تازه نساز؛
یک مزیت مشخص و یک دعوت ساده به اقدام بنویس."""


async def rewrite_compliant(
    s: AsyncSession, acc: Account, text: str, *, reason: str = "", ad_id: int | None = None
) -> dict[str, Any]:
    """Ask Claude for a version of `text` that follows Telegram's ad guidelines; the user edits it before use."""
    ad = None
    if ad_id:
        ad = (await s.execute(select(Ad).where(Ad.account_id == acc.id, Ad.ad_id == ad_id))).scalar_one_or_none()
    before = guidelines.check(text, promote_url=ad.promote_url if ad else None)
    context = {
        "brand": acc.name,
        "bot": f"@{acc.bot_username}" if acc.bot_username else None,
        "target_channel_or_bot": ad.target_label if ad else None,
        "language": "فارسی",
        "max_length": 160,
        "current_text": text,
        "telegram_decline_reason": reason or (ad.decline_reason if ad else "") or None,
        "problems_found": [i["message"] for i in before["issues"]],
    }
    prompt = "بازنویسی منطبق با قوانین تبلیغات تلگرام برای این آگهی:\n\n" + json.dumps(
        context, ensure_ascii=False, indent=1
    )
    key = await app_settings.claude_key(s)
    model = await app_settings.get(s, "claude_model")
    try:
        result = await ClaudeClient(key, model).complete_json(COMPLIANT_SYSTEM, prompt, max_tokens=800)
    except ClaudeError as e:
        raise AppError(str(e), code="claude_error") from None
    new = str(result.get("text") or "").strip().replace("\n", " ")
    if not new:
        raise AppError("Claude متنی برنگرداند؛ دوباره امتحان کنید.", code="claude_error")
    after = guidelines.check(new, promote_url=ad.promote_url if ad else None)
    events.log(s, "text_compliance_rewrite", account_id=acc.id, actor="user", ad_id=ad_id, detail=new[:160])
    return {
        "text": new,
        "notes": [str(x) for x in result.get("notes") or []][:6],
        "check": after,
        "before": before,
        "model": model,
    }
