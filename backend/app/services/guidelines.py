"""Checks of an ad text against Telegram's ad guidelines (https://ads.telegram.org/guidelines).

Only what can be decided from the text itself: length, emoji, decorative characters, line breaks and
lists, vague or repeated wording, invented urgency and clickbait, links (one at most, the same as the
ad's link, no shorteners) and the language. "error" findings are rule breaks Telegram declines ads for;
"warn" findings are likely problems. A `start` parameter on a bot link is allowed.
"""

import re
from typing import Any
from urllib.parse import urlparse

MAX_LEN = 160

URL_RE = re.compile(r"(?:https?://|www\.|\bt\.me/|\btelegram\.me/)[^\s]+", re.I)
SHORTENERS = {
    "bit.ly",
    "t.co",
    "tinyurl.com",
    "goo.gl",
    "cutt.ly",
    "is.gd",
    "ow.ly",
    "rebrand.ly",
    "shorturl.at",
    "rb.gy",
    "tiny.cc",
    "buff.ly",
    "s.id",
    "v.gd",
}
URGENCY = (
    "تا آخر امشب",
    "تا امشب",
    "فقط امروز",
    "فقط تا امروز",
    "فقط امشب",
    "آخرین فرصت",
    "فرصت محدود",
    "فرصت رو از دست نده",
    "فرصت را از دست ندهید",
    "عجله کن",
    "عجله کنید",
    "فقط چند ساعت",
    "چند ساعت دیگه",
    "تموم میشه",
    "تمام می‌شود",
    "ظرفیت محدود",
    "فقط چند نفر",
    "last chance",
    "only today",
    "today only",
    "hurry",
    "limited time",
    "act now",
    "ends tonight",
)
CLICKBAIT = (
    "باورت نمیشه",
    "باورتون نمیشه",
    "باور نمی‌کنید",
    "شوکه",
    "رازی که",
    "هیچ‌کس بهت نمیگه",
    "هیچکس بهت نمیگه",
    "معجزه",
    "۱۰۰٪ تضمینی",
    "100% تضمینی",
    "صد در صد تضمینی",
    "رایگان برای همیشه",
    "you won't believe",
    "shocking",
    "miracle",
    "guaranteed",
)
VAGUE = ("بهترین", "بی‌نظیر", "بی نظیر", "شگفت‌انگیز", "فوق‌العاده", "عالی‌ترین", "best ever", "amazing")
DECORATIVE = set("★☆✪✯✰✔✓✅☑❗❕‼⁉⚡🔥💥💯🚨🔴🟢⭐🌟✨➡⬅⬆⬇▶◀►◄•●○◆◇■□▪▫※")
PERSIAN_RE = re.compile(r"[؀-ۿ]")
LATIN_RE = re.compile(r"[A-Za-z]")


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x1F000 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0x2B00 <= cp <= 0x2BFF
        or cp in (0x203C, 0x2049, 0x3030, 0x303D)
    )


def _fancy_letters(text: str) -> int:
    """Letters from the "mathematical alphanumeric" and enclosed blocks used as decoration (𝐁𝐨𝐥𝐝, Ⓐ, 🅰)."""
    n = 0
    for ch in text:
        cp = ord(ch)
        if 0x1D400 <= cp <= 0x1D7FF or 0x2460 <= cp <= 0x24FF or 0x1F130 <= cp <= 0x1F189 or 0xFF21 <= cp <= 0xFF5A:
            n += 1
    return n


def _host(url: str) -> str:
    if not re.match(r"^[a-z]+://", url, re.I):
        url = "https://" + url
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def _norm_link(url: str) -> str:
    if not re.match(r"^[a-z]+://", url, re.I):
        url = "https://" + url
    p = urlparse(url.rstrip(".,!؟?)»"))
    host = (p.hostname or "").lower().removeprefix("www.").replace("telegram.me", "t.me")
    return f"{host}{p.path.rstrip('/').lower()}"


def check(text: str, *, promote_url: str | None = None, expect_persian: bool = True) -> dict[str, Any]:
    """Return {"issues": [{code, severity, message}], "likely_violation": bool, "length": n}."""
    text = text or ""
    issues: list[dict[str, str]] = []

    def add(code: str, severity: str, message: str) -> None:
        issues.append({"code": code, "severity": severity, "message": message})

    body = text.strip()
    if len(body) > MAX_LEN:
        add("too_long", "error", f"متن {len(body)} کاراکتر است؛ سقف تلگرام {MAX_LEN} کاراکتر است.")
    if not body:
        add("empty", "error", "متن خالی است.")
    if "\n" in body or "\r" in body:
        add("newline", "error", "خط جدید در آگهی تلگرام مجاز نیست؛ متن باید یک پاراگراف باشد.")
    if re.search(r"(^|\s)(?:[-*•▪●]|\d+[.)])\s", body) and ("\n" in body or body.count("•") > 1):
        add("list", "error", "فهرست و بولت در آگهی مجاز نیست.")
    if re.search(r"\[[^\]]+\]", body):
        add("placeholder", "error", "متن هنوز جای خالی مثل [مدت] دارد.")

    emojis = [ch for ch in body if _is_emoji(ch)]
    if len(emojis) > 3:
        add("emoji", "error", f"{len(emojis)} ایموجی دارد؛ ایموجی زیاد یا نمایشی مجاز نیست (حداکثر ۱ تا ۲).")
    elif len(emojis) == 3:
        add("emoji", "warn", "۳ ایموجی دارد؛ بهتر است حداکثر ۱ تا ۲ ایموجی باشد.")
    if re.search(r"(.)\1{2,}", "".join(emojis)) or re.search(r"([\U0001F000-\U0001FAFF☀-➿])\s*\1", body):
        add("emoji_repeat", "error", "ایموجی تکراری پشت سر هم (نمایشی) مجاز نیست.")
    deco = sum(1 for ch in body if ch in DECORATIVE)
    if _fancy_letters(body) >= 2 or deco >= 3:
        add("decorative", "error", "حروف یا علامت‌های نمایشی/تزئینی مجاز نیست.")
    if re.search(r"[!؟?]{2,}|\.{4,}", body):
        add("punctuation", "error", "علامت‌گذاری نمایشی (مثل !!! یا ؟؟) مجاز نیست.")
    caps = re.findall(r"\b[A-Z]{4,}\b", body)
    if [w for w in caps if w not in ("VPN", "HTTP", "HTTPS", "IPTV", "USDT", "TRON")]:
        add("caps", "warn", "کلمه‌های تمام حروف بزرگ لاتین نمایشی به نظر می‌رسند.")

    low = body.lower()
    hit = [p for p in URGENCY if p in low]
    if hit:
        add("urgency", "error", f"فوریت ساختگی («{hit[0]}») مجاز نیست؛ اگر واقعاً مهلت دارد، تاریخ دقیق بنویسید.")
    bait = [p for p in CLICKBAIT if p in low]
    if bait:
        add("clickbait", "error", f"ادعای گمراه‌کننده یا کلیک‌خور («{bait[0]}») مجاز نیست.")
    vague = [p for p in VAGUE if p in low]
    if len(vague) >= 2:
        add("vague", "warn", "عبارت‌های کلی و مبهم («" + "»، «".join(vague[:3]) + "») جای مزیت مشخص را گرفته‌اند.")
    words = [w for w in re.findall(r"[\w؀-ۿ]{3,}", low)]
    rep = {w for w in words if words.count(w) >= 3}
    if rep:
        add("repetition", "warn", f"کلمه‌ی «{sorted(rep)[0]}» بیش از حد تکرار شده است.")

    links = URL_RE.findall(body)
    if len(links) > 1:
        add("links", "error", "بیش از یک لینک در متن مجاز نیست.")
    for link in links:
        if _host(link) in SHORTENERS:
            add("shortener", "error", f"کوتاه‌کننده‌ی لینک ({_host(link)}) مجاز نیست.")
            break
    if links and promote_url:
        target = _norm_link(promote_url)
        if any(_norm_link(link) != target for link in links):
            add("link_mismatch", "error", "لینک داخل متن با لینک اصلی آگهی یکی نیست.")

    if expect_persian and body and not PERSIAN_RE.search(body) and LATIN_RE.search(body):
        add("language", "warn", "متن فارسی نیست؛ زبان آگهی باید با زبان کانال و ربات مقصد یکی باشد.")
    if expect_persian and PERSIAN_RE.search(body):
        latin_words = len(re.findall(r"\b[A-Za-z]{3,}\b", body))
        persian_words = len(re.findall(r"[؀-ۿ]{2,}", body))
        if latin_words > persian_words + 2:
            add("language", "warn", "بیشتر متن انگلیسی است؛ زبان آگهی باید با زبان کانال یکی باشد.")

    errors = sum(1 for i in issues if i["severity"] == "error")
    warns = len(issues) - errors
    return {"issues": issues, "likely_violation": errors > 0 or warns >= 2, "length": len(body)}


def summary(result: dict[str, Any]) -> str:
    return "؛ ".join(i["message"] for i in result["issues"])
