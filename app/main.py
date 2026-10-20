"""Psychonet Telegram Ads manager - web app."""
import hmac
import json
import secrets
import threading
import time
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from datetime import date, timedelta
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import actions, analysis, config, create, db, helpers, metrics, rules, scheduler
from .tgads import TgAdsError

@asynccontextmanager
async def lifespan(_app):
    db.init()
    if config.SCHEDULER_ENABLED and not config.problems():
        scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="Psychonet Ads", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=config.SESSION_SECRET or secrets.token_hex(32),
                   https_only=config.COOKIE_SECURE, same_site="lax", max_age=7 * 86400, session_cookie="pn_session")
app.mount("/static", StaticFiles(directory=config.BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=config.BASE_DIR / "templates")
helpers.register(templates.env)

_fails = defaultdict(deque)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = ("default-src 'self'; img-src 'self' data: https:; style-src 'self'; "
                                               "script-src 'self'; frame-ancestors 'none'; form-action 'self'")
    return resp


# ---------- helpers ----------

def authed(request):
    return request.session.get("auth") is True


def csrf_token(request):
    tok = request.session.get("csrf")
    if not tok:
        tok = secrets.token_urlsafe(24)
        request.session["csrf"] = tok
    return tok


def check_csrf(request, token):
    return hmac.compare_digest(str(token or ""), str(request.session.get("csrf") or "x"))


def flash(request, msg, kind="ok"):
    request.session.setdefault("flash", []).append([kind, msg])


def render(request, name, **ctx):
    s = db.settings()
    ctx.update(request=request, csrf=csrf_token(request), flashes=request.session.pop("flash", []),
               settings=s, account=db.one("SELECT * FROM account WHERE id=1") or {},
               pending_count=(db.one("SELECT COUNT(*) n FROM proposals WHERE status='pending'") or {}).get("n", 0),
               queued_count=(db.one("SELECT COUNT(*) n FROM jobs WHERE status IN ('queued','running')") or {}).get("n", 0),
               last_sync=s.get("last_sync") or {}, last_loop=s.get("last_loop") or {}, nav=name.split(".")[0],
               version=config.APP_VERSION, syncing=scheduler.sync_running())
    return templates.TemplateResponse(request, name, ctx)


def back(path):
    return RedirectResponse(path, status_code=303)


class NeedLogin(Exception):
    pass


class StaleForm(Exception):
    pass


@app.exception_handler(NeedLogin)
async def _need_login(request, exc):
    return back("/login")


@app.exception_handler(StaleForm)
async def _stale_form(request, exc):
    flash(request, "فرم منقضی شده بود (مثلاً از یک تب قدیمی). دوباره امتحان کنید.", "bad")
    ref = urlparse(request.headers.get("referer") or "/")
    return back(ref.path if ref.path.startswith("/") else "/")


def guard(request, token=None, post=False):
    if not authed(request):
        raise NeedLogin()
    if post and not check_csrf(request, token):
        raise StaleForm()


# ---------- auth ----------

def login_ctx(request, error=None):
    # A Secure cookie is never sent back over plain http, so login would silently loop.
    insecure = config.COOKIE_SECURE and request.url.scheme != "https"
    return {"problems": config.problems(), "error": error, "csrf": csrf_token(request), "insecure": insecure,
            "version": config.APP_VERSION}


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if authed(request):
        return back("/")
    return templates.TemplateResponse(request, "login.html", login_ctx(request))


@app.post("/login")
def login(request: Request, password: str = Form(""), csrf: str = Form("")):
    ip = request.client.host if request.client else "?"
    q = _fails[ip]
    while q and q[0] < time.time() - 600:
        q.popleft()
    error = None
    if config.problems():
        error = "اول تنظیمات فایل .env را کامل کنید."
    elif len(q) >= 5:
        error = "تلاش‌های ناموفق زیاد بود. ۱۰ دقیقه بعد دوباره امتحان کنید."
    elif not check_csrf(request, csrf):
        error = "صفحه منقضی شده بود. دوباره امتحان کنید."
    elif not hmac.compare_digest(password.encode(), config.ADMIN_PASSWORD.encode()):
        q.append(time.time())
        error = "رمز اشتباه است."
    if error:
        return templates.TemplateResponse(request, "login.html", login_ctx(request, error), status_code=401)
    request.session.clear()
    request.session["auth"] = True
    db.log("user", "login", None, ip)
    return back("/")


@app.post("/logout")
def logout(request: Request, csrf: str = Form("")):
    if not check_csrf(request, csrf):
        return back("/")
    request.session.clear()
    return back("/login")


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ---------- overview ----------

@app.get("/", response_class=HTMLResponse)
def overview(request: Request):
    guard(request)
    sm = metrics.summary()
    rows = metrics.ad_rows()
    running = [r for r in rows if r["running"]]
    top = sorted([r for r in running if r["starts_28"] >= 10], key=lambda r: r["cps_28"] or 9)[:6]
    worst = sorted([r for r in running if r["spent_28"] >= 0.3], key=lambda r: -(r["cps_28"] or 9))[:6]
    s = db.settings()
    stalled_budget = sum(r["remaining_budget"] or 0 for r in running
                         if r["spent_28"] < s["stalled_spend_28d"] and (r["age_days"] or 0) >= s["stalled_min_age_days"])
    proposals = db.query("""SELECT p.*, a.target_label FROM proposals p LEFT JOIN ads a ON a.ad_id=p.ad_id
                            WHERE p.status='pending' ORDER BY p.created_at DESC LIMIT 6""")
    review = [r for r in rows if r["status"] in ("in_review", "declined", "ready_for_review")]
    return render(request, "overview.html", sm=sm, top=top, worst=worst, proposals=proposals,
                  daily=json.dumps(metrics.daily_totals(60)), stalled_budget=stalled_budget, review=review,
                  running_count=len(running), kind_label=rules.KIND_LABEL)


# ---------- ads ----------

@app.get("/ads", response_class=HTMLResponse)
def ads_page(request: Request, show: str = "running", since: str = ""):
    guard(request)
    try:
        since = date.fromisoformat(since).isoformat() if since else ""
    except ValueError:
        since = ""
    rows = metrics.ad_rows(since or None)
    if show == "running":
        rows = [r for r in rows if r["running"]]
    elif show == "attention":
        rows = [r for r in rows if r["status"] in ("in_review", "declined", "ready_for_review", "on_hold")
                or (r["status"] == "active" and r["is_paused"])]
    rows.sort(key=lambda r: -(r["spent_28"] or 0))
    return render(request, "ads.html", rows=rows, show=show, since=since,
                  since_default=(metrics.today() - timedelta(days=27)).isoformat())


@app.get("/ads/{ad_id}", response_class=HTMLResponse)
def ad_page(request: Request, ad_id: int):
    guard(request)
    row = next((r for r in metrics.ad_rows() if r["ad_id"] == ad_id), None)
    if not row:
        flash(request, "این آگهی پیدا نشد.", "bad")
        return back("/ads")
    jobs = db.query("SELECT * FROM jobs WHERE ad_id=? ORDER BY id DESC LIMIT 20", (ad_id,))
    props = db.query("SELECT * FROM proposals WHERE ad_id=? ORDER BY id DESC LIMIT 20", (ad_id,))
    target = json.loads(row.get("target_json") or "{}")
    return render(request, "ad.html", ad=row, jobs=jobs, props=props, target=target,
                  daily=json.dumps(metrics.ad_daily(ad_id)), kind_label=rules.KIND_LABEL,
                  variants=db.query("SELECT id, name FROM variants ORDER BY id"))


@app.post("/ads/{ad_id}/action")
def ad_action(request: Request, ad_id: int, action: str = Form(...), amount: str = Form(""), csrf: str = Form("")):
    guard(request, csrf, post=True)
    if db.settings().get("automation_paused") and action != "pause":
        flash(request, "اقدام‌ها از تنظیمات متوقف است؛ فقط «توقف» اجرا می‌شود.", "bad")
        return back(f"/ads/{ad_id}")
    if action == "pause":
        actions.enqueue("pause", ad_id)
        flash(request, "توقف در صف رفت.")
    elif action == "resume":
        actions.enqueue("resume", ad_id)
        flash(request, "فعال‌سازی در صف رفت.")
    elif action == "withdraw":
        actions.stop_and_withdraw(ad_id)
        flash(request, f"آگهی متوقف می‌شود و حدود {config.WITHDRAW_DELAY_SECONDS // 60} دقیقه بعد بودجه‌اش برمی‌گردد.")
    elif action == "topup":
        try:
            amt = round(float(amount), 2)
        except ValueError:
            amt = 0
        err = actions.check_topup(amt)
        if err:
            flash(request, err, "bad")
        else:
            actions.enqueue("topup", ad_id, amt)
            flash(request, f"شارژ {amt} TON در صف رفت.")
    return back(f"/ads/{ad_id}")


@app.post("/ads/{ad_id}/meta")
def ad_meta(request: Request, ad_id: int, code: str = Form(""), note: str = Form(""), variant_id: str = Form(""),
            csrf: str = Form("")):
    guard(request, csrf, post=True)
    code = code.strip()
    if code and not create.CODE_RE.match(code):
        flash(request, "کد ردیابی فقط حروف انگلیسی، عدد، _ و - می‌تواند باشد.", "bad")
        return back(f"/ads/{ad_id}")
    other = db.one("SELECT ad_id FROM ad_meta WHERE code=? AND ad_id != ?", (code, ad_id)) if code else None
    if other:
        flash(request, f"این کد مال آگهی {other['ad_id']} است.", "bad")
        return back(f"/ads/{ad_id}")
    with db.tx() as t:
        t.execute("""INSERT INTO ad_meta(ad_id, code, note, variant_id) VALUES (?,?,?,?) ON CONFLICT(ad_id) DO UPDATE SET
                     code=excluded.code, note=excluded.note, variant_id=excluded.variant_id""",
                  (ad_id, code or None, note, int(variant_id) if variant_id else None))
    flash(request, "ذخیره شد.")
    return back(f"/ads/{ad_id}")


# ---------- proposals ----------

@app.get("/proposals", response_class=HTMLResponse)
def proposals_page(request: Request):
    guard(request)
    pending = db.query("""SELECT p.*, a.target_label, a.placement FROM proposals p LEFT JOIN ads a ON a.ad_id=p.ad_id
                          WHERE p.status='pending' ORDER BY p.kind, p.amount DESC""")
    for p in pending:
        p["m"] = json.loads(p["metrics"] or "{}")
    history = db.query("""SELECT p.*, a.target_label FROM proposals p LEFT JOIN ads a ON a.ad_id=p.ad_id
                          WHERE p.status!='pending' ORDER BY COALESCE(p.decided_at, p.created_at) DESC LIMIT 60""")
    groups = {}
    for p in pending:
        groups.setdefault(p["kind"], []).append(p)
    return render(request, "proposals.html", groups=groups, history=history, kind_label=rules.KIND_LABEL,
                  topup_used=actions.topups_last_24h())


@app.post("/proposals/{pid}/{decision}")
def decide(request: Request, pid: int, decision: str, csrf: str = Form("")):
    guard(request, csrf, post=True)
    if decision == "approve":
        p = db.one("SELECT * FROM proposals WHERE id=?", (pid,))
        err = actions.approve(pid)
        if err:
            flash(request, err, "bad")
        elif p and p["kind"] == "refresh":
            return back(f"/new?from={p['ad_id']}")
        else:
            flash(request, "تأیید شد و در صف اجرا رفت.")
    elif decision == "reject":
        actions.reject(pid)
        flash(request, "رد شد.")
    return back("/proposals")


@app.post("/proposals-approve-kind")
def approve_kind(request: Request, kind: str = Form(...), csrf: str = Form("")):
    guard(request, csrf, post=True)
    if kind not in ("stop", "withdraw", "topup"):
        return back("/proposals")
    ok, errs = 0, []
    for p in db.query("SELECT id FROM proposals WHERE status='pending' AND kind=? ORDER BY id", (kind,)):
        err = actions.approve(p["id"])
        if err:
            errs.append(err)
        else:
            ok += 1
    flash(request, f"{ok} پیشنهاد تأیید شد." + (f" {len(errs)} مورد انجام نشد: {errs[0]}" if errs else ""),
          "bad" if errs else "ok")
    return back("/proposals")


@app.post("/rules-run")
def rules_run(request: Request, csrf: str = Form("")):
    guard(request, csrf, post=True)
    r = rules.generate()
    flash(request, "اقدام‌ها متوقف است؛ پیشنهادی ساخته نشد." if r["paused"]
          else f"{r['created']} پیشنهاد جدید، {r['updated']} به‌روز، {r['expired']} منقضی.")
    return back("/proposals")


# ---------- new ad ----------

@app.get("/new", response_class=HTMLResponse)
def new_page(request: Request):
    guard(request)
    src = None
    frm = request.query_params.get("from")
    if frm and frm.isdigit():
        src = db.one("SELECT * FROM ads WHERE ad_id=?", (int(frm),))
    variants = db.query("SELECT * FROM variants WHERE active=1 ORDER BY id")
    used = {}
    for r in db.query("SELECT variant_id, COUNT(*) n FROM ad_meta WHERE variant_id IS NOT NULL GROUP BY variant_id"):
        used[r["variant_id"]] = r["n"]
    suggested = min(variants, key=lambda v: used.get(v["id"], 0))["id"] if variants else None
    prefill = {}
    if src:
        label = (src.get("target_label") or "").split(" | ")[0]
        prefill = {"kind": "bot" if src["placement"] == "bot_banner" else "channel", "username": label,
                   "cpm": src["cpm"], "replace_ad_id": src["ad_id"]}
    return render(request, "new.html", variants=variants, suggested=suggested, prefill=prefill, src=src, form={})


@app.post("/new", response_class=HTMLResponse)
async def new_create(request: Request, photo: UploadFile = File(None)):
    form = dict(await request.form())
    guard(request, form.get("csrf"), post=True)
    form.pop("photo", None)
    ph = None
    if photo is not None and photo.filename:
        content = await photo.read()
        if len(content) > 5 * 1024 * 1024:
            flash(request, "عکس باید کمتر از ۵ مگابایت باشد.", "bad")
            return back("/new")
        ph = {"filename": photo.filename, "content": content, "content_type": photo.content_type or "image/jpeg"}
    try:
        ad = create.create(form, ph)
    except create.CreateError as e:
        variants = db.query("SELECT * FROM variants WHERE active=1 ORDER BY id")
        request.session.setdefault("flash", []).append(["bad", str(e)])
        return render(request, "new.html", variants=variants, suggested=form.get("variant_id"), prefill={}, src=None,
                      form=form)
    except TgAdsError as e:
        flash(request, f"خطای تلگرام: {e.error}", "bad")
        return back("/new")
    flash(request, f"آگهی {ad['ad_id']} ساخته شد و برای بررسی تلگرام فرستاده شد. وضعیتش در همگام‌سازی بعدی به‌روز می‌شود.")
    return back(f"/ads/{ad['ad_id']}")


# ---------- variants ----------

@app.get("/variants", response_class=HTMLResponse)
def variants_page(request: Request):
    guard(request)
    return render(request, "variants.html", rows=analysis.variant_performance())


@app.post("/variants")
def variants_save(request: Request, vid: str = Form(""), name: str = Form(""), text: str = Form(""),
                  op: str = Form("save"), csrf: str = Form("")):
    guard(request, csrf, post=True)
    if op == "toggle" and vid:
        with db.tx() as t:
            t.execute("UPDATE variants SET active = 1 - active WHERE id=?", (int(vid),))
        return back("/variants")
    text = text.strip()
    if len(text) > 160:
        flash(request, f"متن {len(text)} کاراکتر است؛ سقف ۱۶۰ است.", "bad")
        return back("/variants")
    if not name.strip() or not text:
        flash(request, "نام و متن لازم است.", "bad")
        return back("/variants")
    with db.tx() as t:
        if vid:
            used = t.execute("SELECT COUNT(*) FROM ad_meta WHERE variant_id=?", (int(vid),)).fetchone()[0]
            if used:
                t.execute("UPDATE variants SET active=0 WHERE id=?", (int(vid),))
                t.execute("INSERT INTO variants(name, text, active, created_at) VALUES (?,?,1,?)", (name.strip(), text, db.now()))
                flash(request, "این متن روی آگهی‌ها استفاده شده بود؛ برای حفظ آمار، نسخه‌ی جدید ساخته و قبلی غیرفعال شد.")
            else:
                t.execute("UPDATE variants SET name=?, text=? WHERE id=?", (name.strip(), text, int(vid)))
                flash(request, "ذخیره شد.")
        else:
            t.execute("INSERT INTO variants(name, text, active, created_at) VALUES (?,?,1,?)", (name.strip(), text, db.now()))
            flash(request, "متن جدید اضافه شد.")
    return back("/variants")


# ---------- conversions ----------

@app.get("/conversions", response_class=HTMLResponse)
def conversions_page(request: Request):
    guard(request)
    rows, orphan = analysis.by_code()
    recent = db.query("SELECT * FROM conversions ORDER BY ts DESC LIMIT 30")
    base = str(request.base_url).rstrip("/")
    return render(request, "conversions.html", rows=rows, orphan=orphan, recent=recent,
                  endpoint=f"{base}/api/conversions", secret_set=bool(config.CONVERSIONS_SECRET))


@app.post("/conversions/import")
async def conversions_import(request: Request, file: UploadFile = File(...), csrf: str = Form("")):
    guard(request, csrf, post=True)
    text = (await file.read()).decode("utf-8", "replace")
    added, skipped, errors = analysis.record_conversions(analysis.parse_csv(text), source="csv")
    flash(request, f"{added} رویداد ثبت شد، {skipped} تکراری." + (f" {len(errors)} ردیف خطا داشت: {errors[0]}" if errors else ""),
          "bad" if errors and not added else "ok")
    return back("/conversions")


@app.post("/api/conversions")
async def api_conversions(request: Request):
    auth = request.headers.get("authorization", "")
    if not config.CONVERSIONS_SECRET or not hmac.compare_digest(auth, f"Bearer {config.CONVERSIONS_SECRET}"):
        return JSONResponse({"ok": False, "error": "UNAUTHORIZED"}, status_code=401)
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "error": "BAD_JSON"}, status_code=400)
    items = body if isinstance(body, list) else body.get("events", [body]) if isinstance(body, dict) else None
    if not isinstance(items, list):
        return JSONResponse({"ok": False, "error": "EXPECTED_OBJECT_OR_LIST"}, status_code=400)
    if len(items) > 1000:
        return JSONResponse({"ok": False, "error": "TOO_MANY_EVENTS", "max": 1000}, status_code=400)
    added, skipped, errors = analysis.record_conversions(items, source="api")
    return {"ok": not errors or added > 0, "added": added, "duplicates": skipped, "errors": errors}


# ---------- analysis ----------

@app.get("/analysis", response_class=HTMLResponse)
def analysis_page(request: Request):
    guard(request)
    return render(request, "analysis.html", has_key=bool(config.ANTHROPIC_API_KEY), model=config.ANTHROPIC_MODEL,
                  history=db.query("SELECT * FROM analyses ORDER BY id DESC LIMIT 10"))


@app.get("/analysis/export.zip")
def analysis_export(request: Request):
    guard(request)
    data = analysis.export_zip()
    name = f"psychonet-ads-{metrics.today().isoformat()}.zip"
    db.log("user", "export", None, name)
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.post("/analysis/ask")
def analysis_ask(request: Request, question: str = Form(""), csrf: str = Form("")):
    guard(request, csrf, post=True)
    q = question.strip() or "عملکرد ۲۸ روز اخیر را تحلیل کن و قدم‌به‌قدم بگو این هفته چه کار کنم."
    try:
        analysis.ask_claude(q[:2000])
        flash(request, "تحلیل آماده شد.")
    except Exception as e:
        flash(request, str(e), "bad")
    return back("/analysis")


# ---------- settings ----------

NUM_SETTINGS = ["target_cost_per_customer", "min_spend_to_judge", "stop_cost_per_start", "scale_cost_per_start",
                "stalled_spend_28d", "stalled_min_remaining", "stalled_min_age_days", "topup_max_per_ad",
                "topup_daily_cap", "fatigue_age_days", "fatigue_ratio", "min_purchases_to_judge",
                "sync_interval_minutes", "default_cpm_channel", "default_cpm_bot", "default_budget"]


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    guard(request)
    return render(request, "settings.html", has_key=bool(config.ANTHROPIC_API_KEY),
                  conv_secret=bool(config.CONVERSIONS_SECRET))


@app.post("/settings")
async def settings_save(request: Request):
    form = dict(await request.form())
    guard(request, form.get("csrf"), post=True)
    for k in NUM_SETTINGS:
        if k in form:
            try:
                v = float(form[k])
            except ValueError:
                flash(request, f"مقدار {k} عدد نیست.", "bad")
                return back("/settings")
            if v < 0:
                flash(request, f"مقدار {k} نمی‌تواند منفی باشد.", "bad")
                return back("/settings")
            if k == "sync_interval_minutes":
                v = max(15, int(v))
            db.set_setting(k, v)
    if "bot_username" in form:
        db.set_setting("bot_username", form["bot_username"].strip().lstrip("@"))
    db.log("user", "settings", None, "")
    flash(request, "تنظیمات ذخیره شد.")
    return back("/settings")


@app.post("/settings/automation")
def settings_automation(request: Request, paused: str = Form("0"), csrf: str = Form("")):
    guard(request, csrf, post=True)
    db.set_setting("automation_paused", paused == "1")
    db.log("user", "automation", None, "paused" if paused == "1" else "resumed")
    flash(request, "اقدام‌ها متوقف شد." if paused == "1" else "اقدام‌ها دوباره فعال شد.")
    return back("/settings")


@app.post("/settings/kill")
def settings_kill(request: Request, confirm: str = Form(""), csrf: str = Form("")):
    guard(request, csrf, post=True)
    if confirm.strip() != "توقف":
        flash(request, "برای توقف کامل، کلمه‌ی «توقف» را بنویسید.", "bad")
        return back("/settings")
    n = actions.kill_switch()
    db.set_setting("automation_paused", True)
    flash(request, f"{n} آگهی در صف توقف رفت و اقدام‌های دیگر متوقف شد.")
    return back("/settings")


def _sync_in_background():
    try:
        scheduler.sync_now("user")
    except Exception as e:  # shown on every page through last_loop
        db.set_setting("last_loop", {"at": db.now(), "error": f"همگام‌سازی: {e}"})


@app.post("/sync")
def sync_route(request: Request, csrf: str = Form("")):
    guard(request, csrf, post=True)
    if scheduler.sync_running():
        flash(request, "همگام‌سازی در حال اجراست.", "bad")
    else:
        threading.Thread(target=_sync_in_background, daemon=True).start()
        flash(request, "همگام‌سازی شروع شد. چند دقیقه بعد صفحه را تازه کنید.")
    ref = urlparse(request.headers.get("referer") or "/")
    return back(ref.path if ref.path.startswith("/") else "/")


# ---------- log ----------

@app.get("/log", response_class=HTMLResponse)
def log_page(request: Request):
    guard(request)
    return render(request, "log.html",
                  jobs=db.query("""SELECT j.*, a.target_label FROM jobs j LEFT JOIN ads a ON a.ad_id=j.ad_id
                                   ORDER BY j.id DESC LIMIT 80"""),
                  entries=db.query("SELECT * FROM log ORDER BY id DESC LIMIT 200"))
