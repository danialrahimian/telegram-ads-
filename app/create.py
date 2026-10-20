"""Create a new ad with a tracking link (t.me/<bot>?start=<code>)."""
import re

from . import actions, db
from .tgads import TgAdsError, client as tg_client

CODE_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
USER_RE = re.compile(r"^@?[A-Za-z0-9_]{4,32}$")


class CreateError(Exception):
    pass


def suggest_code(username, kind):
    base = re.sub(r"[^A-Za-z0-9]", "", username.lstrip("@")).lower()[:24] or "ad"
    prefix = "c" if kind == "channel" else "b"
    existing = {r["code"] for r in db.query("SELECT code FROM ad_meta WHERE code IS NOT NULL")}
    n = 1
    while f"{prefix}_{base}_{n}" in existing:
        n += 1
    return f"{prefix}_{base}_{n}"


def validate_text(text):
    text = (text or "").strip()
    if not text:
        return "متن آگهی خالی است."
    if len(text) > 160:
        return f"متن {len(text)} کاراکتر است؛ سقف تلگرام ۱۶۰ کاراکتر است."
    if "[" in text or "]" in text:
        return "متن هنوز جای خالی مثل [مدت] دارد. اول آن را با مقدار واقعی پر کنید."
    return None


def create(form, photo=None, actor="user", client=None):
    """form: kind (channel|bot), username, text, variant_id, cpm, budget, code, show_userpic, replace_ad_id."""
    c = client or tg_client()
    s = db.settings()
    kind = form.get("kind")
    if kind not in ("channel", "bot"):
        raise CreateError("نوع جایگاه را انتخاب کنید.")
    username = (form.get("username") or "").strip()
    if not USER_RE.match(username):
        raise CreateError("نام کاربری کانال یا ربات معتبر نیست (مثل @examplechannel).")
    username = "@" + username.lstrip("@")
    err = validate_text(form.get("text"))
    if err:
        raise CreateError(err)
    code = (form.get("code") or "").strip() or suggest_code(username, kind)
    if not CODE_RE.match(code):
        raise CreateError("کد ردیابی فقط می‌تواند حروف انگلیسی، عدد، _ و - داشته باشد.")
    if db.one("SELECT 1 AS x FROM ad_meta WHERE code=?", (code,)):
        raise CreateError("این کد ردیابی قبلاً استفاده شده.")
    try:
        cpm = float(form.get("cpm"))
        budget = float(form.get("budget"))
    except (TypeError, ValueError):
        raise CreateError("CPM و بودجه باید عدد باشند.")
    if cpm <= 0:
        raise CreateError("CPM باید بیشتر از صفر باشد.")
    if budget <= 0:
        raise CreateError("بودجه‌ی اولیه باید بیشتر از صفر باشد؛ تلگرام آگهی بدون بودجه را برای بررسی نمی‌فرستد.")
    if budget > s["topup_max_per_ad"] * 5:
        raise CreateError(f"بودجه‌ی اولیه بیشتر از {s['topup_max_per_ad'] * 5} TON مجاز نیست (پنج برابر سقف شارژ).")
    bot = (s.get("bot_username") or "").lstrip("@")
    if not bot:
        raise CreateError("نام کاربری ربات خودتان را در تنظیمات وارد کنید.")

    acct = c.account()
    if budget and (acct.get("remaining_budget") or 0) + 1e-9 < budget:
        raise CreateError(f"موجودی حساب ({acct.get('remaining_budget')} TON) برای این بودجه کافی نیست.")

    try:
        if kind == "channel":
            c.target_channel(username)
            target = {"type": "channels", "channel_ids": [username]}
            placement = "channel_post"
        else:
            c.target_bot(username)
            target = {"type": "bots", "bot_ids": [username]}
            placement = "bot_banner"
    except TgAdsError as e:
        raise CreateError(f"تلگرام این جایگاه را نپذیرفت: {e.error}")

    params = {
        "title": code, "text": form["text"].strip(), "promote_url": f"https://t.me/{bot}?start={code}",
        "cpm": cpm, "placement": placement, "target": target, "initial_budget": budget, "return_target": True,
    }
    if kind == "bot" and form.get("show_userpic"):
        params["show_userpic"] = True
    try:
        if photo and kind == "channel":
            up = c.upload_photo(photo["filename"], photo["content"], photo["content_type"])
            params["photo_id"] = up["photo_id"]
        # Key tied to the tracking code: a retry after a lost response can never create a second ad.
        ad = c.create_ad(key=f"create-{code}", **params)
    except TgAdsError as e:
        raise CreateError(f"تلگرام آگهی را نساخت: {e.error}")

    # Count the ad toward a text variant only if the text was used as is, so A/B numbers stay honest.
    variant_id = None
    if str(form.get("variant_id") or "").isdigit():
        v = db.one("SELECT id, text FROM variants WHERE id=?", (int(form["variant_id"]),))
        if v and v["text"].strip() == params["text"]:
            variant_id = v["id"]
    with db.tx() as t:
        t.execute("INSERT OR REPLACE INTO ad_meta(ad_id, code, variant_id, note, created_by_app) VALUES (?,?,?,?,1)",
                  (ad["ad_id"], code, variant_id, form.get("note") or ""))
        t.execute("""INSERT OR REPLACE INTO ads(ad_id, title, text, promote_url, cpm, placement, status, is_paused, views,
                     clicks, actions, spent_budget, remaining_budget, created_date, target_type, target_label, synced_at, gone)
                     VALUES (?,?,?,?,?,?,?,?,0,0,0,0,?,?,?,?,?,0)""",
                  (ad["ad_id"], ad.get("title"), ad.get("text"), ad.get("promote_url"), ad.get("cpm"), ad.get("placement"),
                   ad.get("status"), 1 if ad.get("is_paused") else 0, ad.get("remaining_budget", budget),
                   ad.get("created_date") or db.now(), target["type"], username, db.now()))
    db.log(actor, "create_ad", ad["ad_id"], f"{username} کد {code} بودجه {budget}")

    replace = form.get("replace_ad_id")
    if replace:
        actions.stop_and_withdraw(int(replace), actor=actor)
    return ad
