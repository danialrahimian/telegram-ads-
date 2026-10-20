"""Formatting helpers for templates (Shamsi dates, TON amounts, percentages)."""
from datetime import date, datetime, timedelta, timezone

from markupsafe import Markup, escape

TEHRAN = timezone(timedelta(hours=3, minutes=30))
MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]


def g2j(gy, gm, gd):
    """Gregorian to Jalali (standard arithmetic algorithm)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def jdate(value, with_year=True):
    if value in (None, ""):
        return "—"
    if isinstance(value, (int, float)):
        d = datetime.fromtimestamp(value, TEHRAN).date()
    elif isinstance(value, str):
        d = date.fromisoformat(value[:10])
    elif isinstance(value, datetime):
        d = value.date()
    else:
        d = value
    y, m, dd = g2j(d.year, d.month, d.day)
    return f"{dd} {MONTHS[m - 1]} {y}" if with_year else f"{dd} {MONTHS[m - 1]}"


def jdatetime(ts):
    if not ts:
        return "—"
    dt = datetime.fromtimestamp(ts, TEHRAN)
    return f"{jdate(ts)}، {dt:%H:%M}"


def ago(ts):
    if not ts:
        return "هرگز"
    s = int(datetime.now(timezone.utc).timestamp() - ts)
    if s < 60:
        return "همین الان"
    if s < 3600:
        return f"{s // 60} دقیقه پیش"
    if s < 86400:
        return f"{s // 3600} ساعت پیش"
    return f"{s // 86400} روز پیش"


def ton(x, p=2):
    if x is None or x == "":
        return "—"
    return f"{float(x):,.{p}f}"


def cps(x):
    return "—" if x is None else f"{float(x):.3f}"


def pct(x, p=1):
    return "—" if x is None else f"{float(x) * 100:.{p}f}٪"


def num(x):
    return "—" if x is None else f"{int(x):,}"


STATUS = {"active": "فعال", "stopped": "متوقف", "on_hold": "معلق", "in_review": "در حال بررسی",
          "ready_for_review": "آماده‌ی بررسی", "declined": "رد شده"}
PLACEMENT = {"channel_post": "پست کانال", "bot_banner": "بنر ربات", "search_result": "جست‌وجو", "video_banner": "ویدیو"}
JOB = {"pause": "توقف", "resume": "فعال‌سازی", "withdraw": "برداشت بودجه", "topup": "شارژ"}
JOB_STATUS = {"queued": "در صف", "running": "در حال اجرا", "done": "انجام شد", "failed": "ناموفق"}
PROP_STATUS = {"pending": "در انتظار", "approved": "تأیید شد (در صف)", "rejected": "رد شد", "done": "انجام شد",
               "failed": "ناموفق", "expired": "منقضی"}


def status_label(ad):
    if ad.get("status") == "active" and ad.get("is_paused"):
        return "متوقف موقت"
    return STATUS.get(ad.get("status"), ad.get("status") or "—")


def label(x):
    """Usernames like @channel read left to right inside Persian text."""
    if x in (None, ""):
        return "—"
    return Markup('<bdi dir="ltr">') + escape(str(x)) + Markup("</bdi>")


def register(env):
    env.filters.update(t=label, jdate=jdate, jdatetime=jdatetime, ago=ago, ton=ton, cps=cps, pct=pct, num=num)
    env.globals.update(STATUS=STATUS, PLACEMENT=PLACEMENT, JOB=JOB, JOB_STATUS=JOB_STATUS, PROP_STATUS=PROP_STATUS,
                       status_label=status_label)
