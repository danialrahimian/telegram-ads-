"""Referral tags: referrer accounts in the sales bot whose invite links are used as ad links."""

import re

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, Conflict, NotFound
from app.db.base import now_ts
from app.models import Account, Ad, BotUser, ReferralTag
from app.services import events

CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ID_RE = re.compile(r"^\d{3,20}$")


def _validate(name: str, referrer_id: str, start_code: str) -> tuple[str, str, str]:
    name, referrer_id, start_code = name.strip(), referrer_id.strip(), start_code.strip()
    if not name:
        raise AppError("نام برچسب را وارد کنید.")
    if not ID_RE.match(referrer_id):
        raise AppError("شناسه‌ی عددی تلگرام حساب معرف را وارد کنید (فقط عدد).")
    if not start_code:
        start_code = referrer_id
    if not CODE_RE.match(start_code):
        raise AppError("کد start فقط می‌تواند حروف انگلیسی، عدد، _ و - داشته باشد (حداکثر ۶۴ کاراکتر).")
    return name[:80], referrer_id, start_code


async def get(s: AsyncSession, acc: Account, tag_id: int) -> ReferralTag:
    tag = await s.get(ReferralTag, tag_id)
    if tag is None or tag.account_id != acc.id:
        raise NotFound("این برچسب پیدا نشد.")
    return tag


async def _link_ads(s: AsyncSession, acc: Account, tag: ReferralTag) -> None:
    await s.execute(update(Ad).where(Ad.account_id == acc.id, Ad.start_code == tag.start_code).values(tag_id=tag.id))


async def create(
    s: AsyncSession, acc: Account, name: str, referrer_id: str, start_code: str, note: str = ""
) -> ReferralTag:
    name, referrer_id, start_code = _validate(name, referrer_id, start_code)
    dup = (
        await s.execute(
            select(ReferralTag.id).where(ReferralTag.account_id == acc.id, ReferralTag.start_code == start_code)
        )
    ).first()
    if dup:
        raise Conflict("برچسبی با همین کد start وجود دارد.")
    tag = ReferralTag(
        account_id=acc.id,
        name=name,
        referrer_id=referrer_id,
        start_code=start_code,
        note=note.strip()[:500],
        created_ts=now_ts(),
    )
    s.add(tag)
    await s.flush()
    await _link_ads(s, acc, tag)
    events.log(s, "tag_created", account_id=acc.id, actor="user", detail=f"{name} ({start_code})")
    return tag


async def update_tag(
    s: AsyncSession,
    acc: Account,
    tag_id: int,
    *,
    name: str | None,
    referrer_id: str | None,
    start_code: str | None,
    note: str | None,
) -> ReferralTag:
    tag = await get(s, acc, tag_id)
    n, r, c = _validate(
        name if name is not None else tag.name,
        referrer_id if referrer_id is not None else tag.referrer_id,
        start_code if start_code is not None else tag.start_code,
    )
    if c != tag.start_code:
        dup = (
            await s.execute(
                select(ReferralTag.id).where(
                    ReferralTag.account_id == acc.id, ReferralTag.start_code == c, ReferralTag.id != tag.id
                )
            )
        ).first()
        if dup:
            raise Conflict("برچسبی با همین کد start وجود دارد.")
        await s.execute(update(Ad).where(Ad.account_id == acc.id, Ad.tag_id == tag.id).values(tag_id=None))
    if r != tag.referrer_id:
        await s.execute(
            update(BotUser).where(BotUser.account_id == acc.id, BotUser.tag_id == tag.id).values(tag_id=None)
        )
        tag.referred_count = 0
    tag.name, tag.referrer_id, tag.start_code = n, r, c
    if note is not None:
        tag.note = note.strip()[:500]
    await _link_ads(s, acc, tag)
    return tag


async def delete(s: AsyncSession, acc: Account, tag_id: int) -> None:
    tag = await get(s, acc, tag_id)
    await s.delete(tag)
    events.log(s, "tag_deleted", account_id=acc.id, actor="user", detail=tag.name)
