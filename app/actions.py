"""Everything that changes ads on Telegram goes through the job queue here, so every action is
logged, retried safely (idempotency keys) and checked against the spending caps."""
import uuid

from . import config, db
from .tgads import TgAdsError, client as tg_client, floor_amount

MAX_ATTEMPTS = 4


def enqueue(kind, ad_id, amount=None, delay=0, proposal_id=None, actor="user"):
    with db.tx() as t:
        cur = t.execute("""INSERT INTO jobs(kind, ad_id, amount, run_at, proposal_id, created_at, idem_key)
                           VALUES (?,?,?,?,?,?,?)""",
                        (kind, ad_id, amount, db.now() + delay, proposal_id, db.now(), str(uuid.uuid4())))
        jid = cur.lastrowid
    db.log(actor, f"queue:{kind}", ad_id, f"{amount if amount is not None else ''}")
    return jid


def stop_and_withdraw(ad_id, proposal_id=None, actor="user"):
    enqueue("pause", ad_id, proposal_id=proposal_id, actor=actor)
    enqueue("withdraw", ad_id, delay=config.WITHDRAW_DELAY_SECONDS, proposal_id=proposal_id, actor=actor)


def approve(proposal_id, actor="user"):
    p = db.one("SELECT * FROM proposals WHERE id=?", (proposal_id,))
    if not p or p["status"] != "pending":
        return "این پیشنهاد دیگر در انتظار نیست."
    if db.settings().get("automation_paused"):
        return "اقدام‌ها متوقف است. از تنظیمات دوباره روشنش کنید."
    if p["kind"] in ("stop", "withdraw"):
        stop_and_withdraw(p["ad_id"], proposal_id, actor)
        status = "approved"
    elif p["kind"] == "topup":
        err = check_topup(p["amount"])
        if err:
            return err
        enqueue("topup", p["ad_id"], p["amount"], proposal_id=proposal_id, actor=actor)
        status = "approved"
    else:  # refresh is done by creating a new ad from the New ad page
        status = "done"
    with db.tx() as t:
        t.execute("UPDATE proposals SET status=?, decided_at=? WHERE id=?", (status, db.now(), proposal_id))
    db.log(actor, f"approve:{p['kind']}", p["ad_id"], f"پیشنهاد {proposal_id}")
    return None


def reject(proposal_id, actor="user"):
    with db.tx() as t:
        t.execute("UPDATE proposals SET status='rejected', decided_at=? WHERE id=? AND status='pending'",
                  (db.now(), proposal_id))
    db.log(actor, "reject", None, f"پیشنهاد {proposal_id}")


def topups_last_24h():
    r = db.one("""SELECT SUM(amount) s FROM jobs WHERE kind='topup' AND status IN ('queued','running','done')
                  AND created_at >= ?""", (db.now() - 86400,))
    return (r or {}).get("s") or 0.0


def check_topup(amount):
    s = db.settings()
    if amount <= 0:
        return "مبلغ شارژ باید بیشتر از صفر باشد."
    if amount > s["topup_max_per_ad"] + 1e-9:
        return f"سقف شارژ هر آگهی {s['topup_max_per_ad']} TON است."
    used = topups_last_24h()
    if used + amount > s["topup_daily_cap"] + 1e-9:
        return f"سقف شارژ روزانه {s['topup_daily_cap']} TON است و {used:.2f} TON در ۲۴ ساعت اخیر استفاده شده."
    return None


def kill_switch(actor="user"):
    ads = db.query("SELECT ad_id FROM ads WHERE gone=0 AND status='active' AND is_paused=0")
    for a in ads:
        enqueue("pause", a["ad_id"], actor=actor)
    with db.tx() as t:
        t.execute("UPDATE proposals SET status='rejected', decided_at=?, result='توقف کامل' WHERE status='pending'",
                  (db.now(),))
    db.log(actor, "kill_switch", None, f"{len(ads)} آگهی برای توقف در صف رفت")
    return len(ads)


def _finish(job, status, result):
    with db.tx() as t:
        t.execute("UPDATE jobs SET status=?, result=? WHERE id=?", (status, result, job["id"]))
        if job["proposal_id"]:
            left = t.execute("SELECT COUNT(*) FROM jobs WHERE proposal_id=? AND status IN ('queued','running')",
                             (job["proposal_id"],)).fetchone()[0]
            failed = t.execute("SELECT COUNT(*) FROM jobs WHERE proposal_id=? AND status='failed'",
                               (job["proposal_id"],)).fetchone()[0]
            if left == 0:
                t.execute("UPDATE proposals SET status=?, result=? WHERE id=?",
                          ("failed" if failed else "done", result, job["proposal_id"]))
    db.log("worker", f"{job['kind']}:{status}", job["ad_id"], result)


def _retry(job, msg, delay=60):
    if job["attempts"] + 1 >= MAX_ATTEMPTS:
        return _finish(job, "failed", msg)
    with db.tx() as t:
        t.execute("UPDATE jobs SET status='queued', attempts=attempts+1, run_at=?, result=? WHERE id=?",
                  (db.now() + delay, msg, job["id"]))


def _refresh_ad(c, ad_id):
    ad = c.ads_by_id([ad_id]).get(ad_id)
    if ad:
        with db.tx() as t:
            t.execute("UPDATE ads SET status=?, is_paused=?, remaining_budget=?, spent_budget=? WHERE ad_id=?",
                      (ad.get("status"), 1 if ad.get("is_paused") else 0, ad.get("remaining_budget", 0),
                       ad.get("spent_budget", 0), ad_id))
    return ad


def run_job(job, c):
    kind, aid = job["kind"], job["ad_id"]
    if kind == "pause":
        c.pause(aid, True)
        _refresh_ad(c, aid)
        return _finish(job, "done", "متوقف شد")
    if kind == "resume":
        c.pause(aid, False)
        _refresh_ad(c, aid)
        return _finish(job, "done", "دوباره فعال شد")
    if kind == "withdraw":
        ad = _refresh_ad(c, aid)
        if not ad:
            return _finish(job, "failed", "آگهی پیدا نشد")
        if not ad.get("is_paused") and ad.get("status") == "active":
            c.pause(aid, True)
            return _retry(job, "آگهی هنوز فعال بود؛ متوقف شد و برداشت بعداً انجام می‌شود", config.WITHDRAW_DELAY_SECONDS)
        amount = floor_amount(ad.get("remaining_budget", 0))
        if amount <= 0:
            return _finish(job, "done", "بودجه‌ای برای برداشت نبود")
        c.withdraw(aid, amount, key=job["idem_key"])
        _refresh_ad(c, aid)
        return _finish(job, "done", f"{amount} TON به حساب برگشت")
    if kind == "topup":
        acct = c.account()
        if (acct.get("remaining_budget") or 0) + 1e-9 < job["amount"]:
            waiting = db.one("SELECT COUNT(*) n FROM jobs WHERE kind='withdraw' AND status IN ('queued','running')")["n"]
            if waiting and job["created_at"] > db.now() - 3 * 3600:
                # Budget is on its way back from paused ads; try again after the withdrawals.
                with db.tx() as t:
                    t.execute("UPDATE jobs SET status='queued', run_at=?, result=? WHERE id=?",
                              (db.now() + config.WITHDRAW_DELAY_SECONDS + 30,
                               "منتظر برگشت بودجه از آگهی‌های متوقف‌شده", job["id"]))
                return None
            return _finish(job, "failed", f"موجودی حساب ({acct.get('remaining_budget')}) کافی نیست")
        c.topup(aid, job["amount"], key=job["idem_key"])
        _refresh_ad(c, aid)
        return _finish(job, "done", f"{job['amount']} TON شارژ شد")
    return _finish(job, "failed", f"نوع ناشناخته: {kind}")


def process_due(client=None):
    if db.settings().get("automation_paused"):
        due = db.query("SELECT * FROM jobs WHERE status='queued' AND run_at<=? AND kind='pause' ORDER BY id", (db.now(),))
    else:
        due = db.query("SELECT * FROM jobs WHERE status='queued' AND run_at<=? ORDER BY id", (db.now(),))
    if not due:
        return 0
    c = client or tg_client()
    for job in due:
        with db.tx() as t:
            got = t.execute("UPDATE jobs SET status='running' WHERE id=? AND status='queued'", (job["id"],)).rowcount
        if not got:
            continue
        try:
            run_job(job, c)
        except TgAdsError as e:
            if e.error == "IDEMPOTENT_PARAM_MISMATCH":  # the amount changed since the last try
                with db.tx() as t:
                    t.execute("UPDATE jobs SET idem_key=? WHERE id=?", (str(uuid.uuid4()), job["id"]))
            # Telegram refuses withdrawals within 10 minutes of the ad being active: wait and try again.
            delay = config.WITHDRAW_DELAY_SECONDS if job["kind"] == "withdraw" else 60
            _retry(job, f"خطای تلگرام: {e.error}", delay)
        except Exception as e:
            _retry(job, f"خطا: {e}")
    return len(due)
