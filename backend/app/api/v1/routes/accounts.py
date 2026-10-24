"""Accounts, their connections, sync control and dashboard data."""

from fastapi import APIRouter
from fastapi.responses import Response
from sqlalchemy import func, select

from app.api.deps import AccountDep, Auth, Session
from app.core import crypto
from app.core.errors import AppError
from app.models import Job, Proposal
from app.schemas.requests import AccountCreateIn, AccountUpdateIn, BotConnectionIn, KillIn, SyncIn, TelegramTokenIn
from app.services import accounts, actions, analysis, app_settings, bot_diag, metrics, sync
from app.workers.scheduler import KINDS, scheduler

router = APIRouter(prefix="/accounts", tags=["accounts"], dependencies=[Auth])


async def _public(s: Session, acc: AccountDep) -> dict:
    pending = (
        await s.execute(
            select(func.count(Proposal.id)).where(Proposal.account_id == acc.id, Proposal.status == "pending")
        )
    ).scalar_one()
    queued = (
        await s.execute(
            select(func.count(Job.id)).where(Job.account_id == acc.id, Job.status.in_(("queued", "running")))
        )
    ).scalar_one()
    return {
        **accounts.public(acc),
        "pending_proposals": pending,
        "queued_jobs": queued,
        "syncing": scheduler.running_kinds(acc.id),
    }


@router.get("")
async def list_accounts(s: Session) -> dict:
    return {"accounts": [await _public(s, a) for a in await accounts.list_accounts(s)]}


@router.post("", status_code=201)
async def create_account(body: AccountCreateIn, s: Session) -> dict:
    acc = await accounts.create(s, body.name, body.slug, body.color)
    await s.commit()
    return await _public(s, acc)


@router.get("/{slug}")
async def get_account(acc: AccountDep, s: Session) -> dict:
    return await _public(s, acc)


@router.patch("/{slug}")
async def update_account(body: AccountUpdateIn, acc: AccountDep, s: Session) -> dict:
    await accounts.update(
        s, acc, name=body.name, color=body.color, settings_patch=body.settings, automation_paused=body.automation_paused
    )
    await s.commit()
    return await _public(s, acc)


@router.delete("/{slug}", status_code=204)
async def delete_account(acc: AccountDep, s: Session) -> Response:
    await s.delete(acc)
    await s.commit()
    return Response(status_code=204)


# ---- connections ----


@router.put("/{slug}/telegram")
async def set_telegram(body: TelegramTokenIn, acc: AccountDep, s: Session) -> dict:
    result = await accounts.set_telegram_token(s, acc, body.token.get_secret_value())
    await s.commit()
    if result["ok"]:
        scheduler.trigger(acc.id, "fast", force=True)
    return {"check": result, "account": await _public(s, acc)}


@router.delete("/{slug}/telegram")
async def remove_telegram(acc: AccountDep, s: Session) -> dict:
    await accounts.clear_telegram_token(s, acc)
    await s.commit()
    return await _public(s, acc)


@router.post("/{slug}/telegram/check")
async def check_telegram(acc: AccountDep, s: Session) -> dict:
    result = await accounts.check_telegram(s, acc)
    await s.commit()
    return {"check": result, "account": await _public(s, acc)}


@router.put("/{slug}/bot")
async def set_bot(body: BotConnectionIn, acc: AccountDep, s: Session) -> dict:
    key = body.api_key.get_secret_value() if body.api_key is not None else None
    result = await accounts.set_bot(s, acc, base_url=body.base_url, api_key=key, username=body.username)
    await s.commit()
    if result["status"] in ("ok", "warn"):
        scheduler.trigger(acc.id, "bot", force=True)
    return {"check": result, "account": await _public(s, acc)}


@router.post("/{slug}/bot/check")
async def check_bot(acc: AccountDep, s: Session) -> dict:
    result = await accounts.check_bot(s, acc)
    await s.commit()
    return {"check": result, "account": await _public(s, acc)}


async def _secrets(s: Session, acc: AccountDep) -> list[str]:
    return [
        crypto.decrypt(acc.bot_api_key_enc) or "",
        crypto.decrypt(acc.tg_token_enc) or "",
        await app_settings.claude_key(s) or "",
    ]


@router.post("/{slug}/bot/diagnose")
async def diagnose_bot(acc: AccountDep, s: Session) -> dict:
    """Try every request the panel needs, one by one, and explain each failure (no key in the result)."""
    report = await bot_diag.diagnose(s, acc)
    await s.commit()
    return {"report": report, "text": bot_diag.report_text(report, await _secrets(s, acc))}


@router.get("/{slug}/bot/diagnose")
async def last_diagnosis(acc: AccountDep, s: Session) -> dict:
    report = (acc.sync_state or {}).get("bot_diag")
    if not report:
        return {"report": None, "text": ""}
    return {"report": report, "text": bot_diag.report_text(report, await _secrets(s, acc))}


# ---- sync & live data ----


@router.post("/{slug}/sync")
async def sync_now(body: SyncIn, acc: AccountDep) -> dict:
    kinds = list(KINDS) if body.kind == "all" else [body.kind]
    bot_ready = bool(acc.bot_base_url and acc.bot_api_key_enc)
    kinds = [k for k in kinds if (bot_ready if k == "bot" else bool(acc.tg_token_enc))]
    if not kinds:
        raise AppError("اتصال‌های این حساب هنوز تنظیم نشده‌اند.", code="not_configured")
    if not scheduler.started:  # background worker disabled: run inline
        errors = []
        for k in sorted(kinds, key=KINDS.index):
            try:
                await sync.run(acc.id, k)
            except Exception as e:
                errors.append(f"{k}: {e}")
        return {"started": kinds, "running": [], "errors": errors}
    started = [k for k in kinds if scheduler.trigger(acc.id, k)]
    return {"started": started, "running": scheduler.running_kinds(acc.id)}


@router.get("/{slug}/live")
async def live(acc: AccountDep, s: Session) -> dict:
    return {
        "account": await _public(s, acc),
        "live": await metrics.live(s, acc),
        "ui_refresh_seconds": await app_settings.get(s, "ui_refresh_seconds"),
    }


@router.get("/{slug}/dashboard")
async def dashboard(acc: AccountDep, s: Session, days: int = 60) -> dict:
    days = max(7, min(days, 180))
    return {"summary": await metrics.summary(s, acc), "daily": await metrics.daily(s, acc, days)}


@router.post("/{slug}/kill")
async def kill(body: KillIn, acc: AccountDep, s: Session) -> dict:
    if body.confirm.strip() != "توقف":
        raise AppError("برای توقف کامل، کلمه‌ی «توقف» را بنویسید.")
    n = await actions.kill_switch(s, acc)
    await s.commit()
    return {"paused_ads": n}


@router.get("/{slug}/export.zip")
async def export(acc: AccountDep, s: Session) -> Response:
    data = await analysis.export_zip(s, acc)
    name = f"tgads-{acc.slug}-{metrics.today_utc().isoformat()}.zip"
    return Response(
        data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )
