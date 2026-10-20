from datetime import date

from fastapi import APIRouter, File, Form, UploadFile
from sqlalchemy import select

from app.api.deps import AccountDep, Auth, Session
from app.core.errors import AppError, NotFound
from app.models import Ad, AdStat, Job, Proposal
from app.schemas.requests import AdActionIn, AdCreateIn, AdEditIn
from app.services import actions, ads, metrics
from app.services.rules import KIND_LABEL

router = APIRouter(prefix="/accounts/{slug}/ads", tags=["ads"], dependencies=[Auth])

MAX_PHOTO = 5 * 1024 * 1024


@router.get("")
async def list_ads(acc: AccountDep, s: Session, since: str | None = None) -> dict:
    if since:
        try:
            since = date.fromisoformat(since).isoformat()
        except ValueError:
            since = None
    return {"ads": await metrics.ad_rows(s, acc, since), "since": since}


@router.get("/{ad_id}")
async def get_ad(ad_id: int, acc: AccountDep, s: Session) -> dict:
    row = next((r for r in await metrics.ad_rows(s, acc) if r["ad_id"] == ad_id), None)
    if row is None:
        raise NotFound("این آگهی پیدا نشد.")
    target = (await s.execute(select(Ad.target).where(Ad.account_id == acc.id, Ad.ad_id == ad_id))).scalar_one()
    daily = [
        {"day": d.day, "views": d.views, "clicks": d.clicks, "starts": d.actions, "spent": d.spent}
        for d in (
            await s.execute(
                select(AdStat).where(AdStat.account_id == acc.id, AdStat.ad_id == ad_id).order_by(AdStat.day)
            )
        ).scalars()
    ]
    jobs = [
        {
            "id": j.id,
            "kind": j.kind,
            "amount": j.amount,
            "status": j.status,
            "result": j.result,
            "created_ts": j.created_ts,
            "run_at": j.run_at,
        }
        for j in (
            await s.execute(
                select(Job).where(Job.account_id == acc.id, Job.ad_id == ad_id).order_by(Job.id.desc()).limit(20)
            )
        ).scalars()
    ]
    props = [
        {
            "id": p.id,
            "kind": p.kind,
            "label": KIND_LABEL.get(p.kind, p.kind),
            "amount": p.amount,
            "status": p.status,
            "reason": p.reason,
            "result": p.result,
            "created_ts": p.created_ts,
        }
        for p in (
            await s.execute(
                select(Proposal)
                .where(Proposal.account_id == acc.id, Proposal.ad_id == ad_id)
                .order_by(Proposal.id.desc())
                .limit(20)
            )
        ).scalars()
    ]
    return {"ad": row, "target": target, "daily": daily, "jobs": jobs, "proposals": props}


@router.post("/{ad_id}/actions")
async def ad_action(ad_id: int, body: AdActionIn, acc: AccountDep, s: Session) -> dict:
    msg = await actions.ad_action(s, acc, ad_id, body.action, body.amount)
    await s.commit()
    return {"message": msg}


@router.patch("/{ad_id}")
async def edit_ad(ad_id: int, body: AdEditIn, acc: AccountDep, s: Session) -> dict:
    data = body.model_dump(exclude_unset=True)
    if data.pop("clear_tag", False):
        data["tag_id"] = None
    _, remote = await ads.edit(s, acc, ad_id, data)
    await s.commit()
    return {
        "remote_changed": remote,
        "message": "تغییر به تلگرام فرستاده شد؛ آگهی دوباره بررسی می‌شود." if remote else "ذخیره شد.",
    }


@router.post("", status_code=201)
async def create_ad(
    acc: AccountDep, s: Session, payload: str = Form(...), photo: UploadFile | None = File(None)
) -> dict:
    """multipart: `payload` is the JSON body (AdCreateIn), `photo` an optional image."""
    body = AdCreateIn.model_validate_json(payload)
    ph = None
    if photo is not None and photo.filename:
        content = await photo.read()
        if len(content) > MAX_PHOTO:
            raise AppError("عکس باید کمتر از ۵ مگابایت باشد.")
        if (photo.content_type or "") not in ("image/jpeg", "image/png"):
            raise AppError("عکس باید JPG یا PNG باشد.")
        ph = (photo.filename, content, photo.content_type or "image/jpeg")
    ad = await ads.create(s, acc, body.model_dump(), ph)
    await s.commit()
    return {"ad_id": ad.ad_id, "message": f"آگهی {ad.ad_id} ساخته شد و برای بررسی تلگرام فرستاده شد."}
