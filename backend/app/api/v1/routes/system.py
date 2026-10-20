"""Global endpoints: overview of all accounts, app settings, system info."""

import asyncio

import httpx
from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import Auth, Session
from app.core.config import get_settings
from app.core.errors import AppError
from app.integrations.anthropic import ClaudeClient, ClaudeError
from app.models import Event, Job, Proposal
from app.schemas.requests import AppSettingsIn
from app.services import accounts, app_settings, events, metrics
from app.workers.scheduler import scheduler

router = APIRouter(tags=["system"], dependencies=[Auth])
_ip_cache: dict[str, str] = {}


async def server_ip() -> str:
    if "ip" in _ip_cache:
        return _ip_cache["ip"]
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                r = await c.get(url)
            ip = r.text.strip()
            if r.status_code == 200 and 6 <= len(ip) <= 45:
                _ip_cache["ip"] = ip
                return ip
        except httpx.HTTPError:
            continue
    return ""


@router.get("/overview")
async def overview(s: Session) -> dict:
    out = []
    for acc in await accounts.list_accounts(s):
        summ = await metrics.summary(s, acc) if acc.tg_token_enc else None
        pending = (
            await s.execute(
                select(func.count(Proposal.id)).where(Proposal.account_id == acc.id, Proposal.status == "pending")
            )
        ).scalar_one()
        out.append(
            {
                **accounts.public(acc),
                "summary": summ,
                "pending_proposals": pending,
                "syncing": scheduler.running_kinds(acc.id),
            }
        )
    return {"accounts": out}


@router.get("/settings")
async def get_app_settings(s: Session) -> dict:
    return await app_settings.public(s)


@router.put("/settings")
async def put_app_settings(body: AppSettingsIn, s: Session) -> dict:
    if body.claude_api_key is not None:
        await app_settings.set_claude_key(s, body.claude_api_key.get_secret_value())
    if body.claude_model:
        await app_settings.put(s, "claude_model", body.claude_model)
    if body.ui_refresh_seconds:
        await app_settings.put(s, "ui_refresh_seconds", body.ui_refresh_seconds)
    events.log(s, "app_settings", actor="user")
    await s.commit()
    return await app_settings.public(s)


@router.post("/settings/claude/test")
async def test_claude(s: Session) -> dict:
    key = await app_settings.claude_key(s)
    model = str(await app_settings.get(s, "claude_model"))
    try:
        text = await ClaudeClient(key, model).complete("Reply with exactly: OK", "ping", max_tokens=10)
    except ClaudeError as e:
        raise AppError(str(e), code="claude_error") from None
    return {"ok": True, "model": model, "reply": text.strip()[:40]}


@router.get("/system")
async def system(s: Session) -> dict:
    settings = get_settings()
    jobs = (await s.execute(select(func.count(Job.id)).where(Job.status.in_(("queued", "running"))))).scalar_one()
    try:
        ip = await asyncio.wait_for(server_ip(), timeout=12)
    except TimeoutError:
        ip = ""
    return {
        "version": settings.app_version,
        "server_ip": ip,
        "scheduler_tick": scheduler.last_tick,
        "queued_jobs": jobs,
        "ui_refresh_seconds": await app_settings.get(s, "ui_refresh_seconds"),
        "min_sync_seconds": settings.min_sync_seconds,
    }


@router.get("/events")
async def global_events(s: Session, limit: int = 100) -> dict:
    rows = (await s.execute(select(Event).order_by(Event.id.desc()).limit(min(limit, 500)))).scalars()
    return {
        "events": [
            {
                "id": e.id,
                "ts": e.ts,
                "account_id": e.account_id,
                "actor": e.actor,
                "action": e.action,
                "ad_id": e.ad_id,
                "level": e.level,
                "detail": e.detail,
            }
            for e in rows
        ]
    }
