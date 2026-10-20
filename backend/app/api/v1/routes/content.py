"""Proposals, text library, referral tags, sales, Claude analysis and activity for one account."""

from fastapi import APIRouter
from fastapi.responses import Response
from sqlalchemy import select

from app.api.deps import AccountDep, Auth, Session
from app.core.errors import AppError
from app.db.base import now_ts
from app.models import Ad, AiAnalysis, Event, Job, Proposal, TextVariant
from app.schemas.requests import (
    AnalysisIn,
    ApproveKindIn,
    ReferrerLookupIn,
    TagIn,
    TagUpdateIn,
    TextAnalyzeIn,
    TextIn,
    TextUpdateIn,
)
from app.services import accounts, actions, analysis, metrics, referrals, rules, texts

router = APIRouter(prefix="/accounts/{slug}", dependencies=[Auth])


# ---------------------------------------------------------------- proposals


@router.get("/proposals", tags=["proposals"])
async def list_proposals(acc: AccountDep, s: Session) -> dict:
    labels = {
        a.ad_id: (a.target_label, a.placement, a.title)
        for a in (await s.execute(select(Ad).where(Ad.account_id == acc.id))).scalars()
    }

    def row(p: Proposal) -> dict:
        lab = labels.get(p.ad_id, ("", "", ""))
        return {
            "id": p.id,
            "ad_id": p.ad_id,
            "kind": p.kind,
            "label": rules.KIND_LABEL.get(p.kind, p.kind),
            "amount": p.amount,
            "reason": p.reason,
            "metrics": p.metrics,
            "status": p.status,
            "created_ts": p.created_ts,
            "decided_ts": p.decided_ts,
            "result": p.result,
            "target_label": lab[0],
            "placement": lab[1],
            "title": lab[2],
        }

    pending = (
        await s.execute(
            select(Proposal)
            .where(Proposal.account_id == acc.id, Proposal.status == "pending")
            .order_by(Proposal.kind, Proposal.amount.desc())
        )
    ).scalars()
    history = (
        await s.execute(
            select(Proposal)
            .where(Proposal.account_id == acc.id, Proposal.status != "pending")
            .order_by(Proposal.decided_ts.desc(), Proposal.id.desc())
            .limit(80)
        )
    ).scalars()
    return {
        "pending": [row(p) for p in pending],
        "history": [row(p) for p in history],
        "topup_used_24h": await actions.topups_last_24h(s, acc),
        "topup_daily_cap": accounts.settings_of(acc)["topup_daily_cap"],
        "labels": rules.KIND_LABEL,
    }


@router.post("/proposals/{pid}/approve", tags=["proposals"])
async def approve(pid: int, acc: AccountDep, s: Session) -> dict:
    kind = await actions.approve(s, acc, pid)
    await s.commit()
    p = await s.get(Proposal, pid)
    return {
        "kind": kind,
        "ad_id": p.ad_id if p else None,
        "message": "برای تازه کردن متن، آگهی تازه بسازید." if kind == "refresh" else "تأیید شد و در صف اجرا رفت.",
    }


@router.post("/proposals/{pid}/reject", tags=["proposals"])
async def reject(pid: int, acc: AccountDep, s: Session) -> dict:
    await actions.reject(s, acc, pid)
    await s.commit()
    return {"message": "رد شد؛ تا یک هفته دوباره پیشنهاد نمی‌شود."}


@router.post("/proposals/approve-kind", tags=["proposals"])
async def approve_kind(body: ApproveKindIn, acc: AccountDep, s: Session) -> dict:
    ok, errors = 0, []
    ids = (
        await s.execute(
            select(Proposal.id)
            .where(Proposal.account_id == acc.id, Proposal.status == "pending", Proposal.kind == body.kind)
            .order_by(Proposal.id)
        )
    ).scalars()
    for pid in list(ids):
        try:
            await actions.approve(s, acc, pid)
            ok += 1
        except AppError as e:
            errors.append(e.detail)
    await s.commit()
    return {"approved": ok, "errors": errors}


@router.post("/proposals/run", tags=["proposals"])
async def run_rules(acc: AccountDep) -> dict:
    return await rules.generate(acc.id)


# ---------------------------------------------------------------- texts


@router.get("/texts", tags=["texts"])
async def list_texts(acc: AccountDep, s: Session) -> dict:
    perf = await texts.performance(s, acc)
    rows = (
        await s.execute(
            select(TextVariant)
            .where(TextVariant.account_id == acc.id)
            .order_by(TextVariant.active.desc(), TextVariant.id)
        )
    ).scalars()
    return {"texts": [texts.public(v, perf.get(v.id)) for v in rows]}


@router.post("/texts", tags=["texts"], status_code=201)
async def create_text(body: TextIn, acc: AccountDep, s: Session) -> dict:
    v = await texts.create(s, acc, body.name, body.text)
    await s.commit()
    return texts.public(v)


@router.post("/texts/import", tags=["texts"])
async def import_texts(acc: AccountDep, s: Session) -> dict:
    n = await texts.import_from_ads(s, acc)
    await s.commit()
    return {"imported": n}


@router.patch("/texts/{vid}", tags=["texts"])
async def update_text(vid: int, body: TextUpdateIn, acc: AccountDep, s: Session) -> dict:
    v = await texts.update(s, acc, vid, name=body.name, text=body.text, active=body.active)
    await s.commit()
    return {**texts.public(v), "versioned": v.id != vid}


@router.delete("/texts/{vid}", tags=["texts"], status_code=204)
async def delete_text(vid: int, acc: AccountDep, s: Session) -> Response:
    await texts.delete(s, acc, vid)
    await s.commit()
    return Response(status_code=204)


@router.post("/texts/{vid}/analyze", tags=["texts"])
async def analyze_text(vid: int, body: TextAnalyzeIn, acc: AccountDep, s: Session) -> dict:
    result = await texts.analyze(s, acc, vid, body.goal)
    await s.commit()
    return result


# ---------------------------------------------------------------- referral tags & sales


@router.get("/tags", tags=["tags"])
async def list_tags(acc: AccountDep, s: Session) -> dict:
    return {"tags": await metrics.tag_rows(s, acc)}


@router.post("/tags", tags=["tags"], status_code=201)
async def create_tag(body: TagIn, acc: AccountDep, s: Session) -> dict:
    tag = await referrals.create(s, acc, body.name, body.referrer_id, body.start_code, body.note)
    await s.commit()
    return {"id": tag.id}


@router.patch("/tags/{tag_id}", tags=["tags"])
async def update_tag(tag_id: int, body: TagUpdateIn, acc: AccountDep, s: Session) -> dict:
    await referrals.update_tag(
        s, acc, tag_id, name=body.name, referrer_id=body.referrer_id, start_code=body.start_code, note=body.note
    )
    await s.commit()
    return {"ok": True}


@router.delete("/tags/{tag_id}", tags=["tags"], status_code=204)
async def delete_tag(tag_id: int, acc: AccountDep, s: Session) -> Response:
    await referrals.delete(s, acc, tag_id)
    await s.commit()
    return Response(status_code=204)


@router.post("/tags/lookup", tags=["tags"])
async def lookup_referrer(body: ReferrerLookupIn, acc: AccountDep) -> dict:
    if not body.referrer_id.isdigit():
        raise AppError("شناسه‌ی عددی تلگرام را وارد کنید.")
    return await accounts.lookup_referrer(acc, body.referrer_id)


@router.get("/sales", tags=["tags"])
async def sales(acc: AccountDep, s: Session, days: int = 30) -> dict:
    return {
        "overview": await metrics.sales_overview(s, acc, max(1, min(days, 365))),
        "tags": await metrics.tag_rows(s, acc),
    }


# ---------------------------------------------------------------- Claude analysis


@router.get("/analysis", tags=["analysis"])
async def list_analyses(acc: AccountDep, s: Session) -> dict:
    rows = (
        await s.execute(
            select(AiAnalysis)
            .where(AiAnalysis.account_id == acc.id, AiAnalysis.kind == "account")
            .order_by(AiAnalysis.id.desc())
            .limit(20)
        )
    ).scalars()
    return {
        "analyses": [
            {
                "id": a.id,
                "question": a.question,
                "output": a.output,
                "model": a.model,
                "created_at": a.created_at.isoformat(),
            }
            for a in rows
        ]
    }


@router.post("/analysis", tags=["analysis"])
async def run_analysis(body: AnalysisIn, acc: AccountDep, s: Session) -> dict:
    row = await analysis.ask(s, acc, body.question)
    await s.commit()
    return {
        "id": row.id,
        "question": row.question,
        "output": row.output,
        "model": row.model,
        "created_at": row.created_at.isoformat(),
    }


# ---------------------------------------------------------------- activity


@router.get("/activity", tags=["activity"])
async def activity(acc: AccountDep, s: Session) -> dict:
    labels = {a.ad_id: a.target_label for a in (await s.execute(select(Ad).where(Ad.account_id == acc.id))).scalars()}
    jobs = (await s.execute(select(Job).where(Job.account_id == acc.id).order_by(Job.id.desc()).limit(100))).scalars()
    evs = (
        await s.execute(select(Event).where(Event.account_id == acc.id).order_by(Event.id.desc()).limit(300))
    ).scalars()
    return {
        "now": now_ts(),
        "jobs": [
            {
                "id": j.id,
                "kind": j.kind,
                "label": actions.JOB_LABEL.get(j.kind, j.kind),
                "ad_id": j.ad_id,
                "target_label": labels.get(j.ad_id, ""),
                "amount": j.amount,
                "status": j.status,
                "attempts": j.attempts,
                "result": j.result,
                "created_ts": j.created_ts,
                "run_at": j.run_at,
            }
            for j in jobs
        ],
        "events": [
            {
                "id": e.id,
                "ts": e.ts,
                "actor": e.actor,
                "action": e.action,
                "ad_id": e.ad_id,
                "level": e.level,
                "detail": e.detail,
            }
            for e in evs
        ],
    }
