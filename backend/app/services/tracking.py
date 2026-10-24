"""Per-ad sales tracking modes behind one interface.

The sales bot attributes a new user to a source only when the `start` parameter is the numeric id of a
user that already exists in the bot (the referral system, `affiliates_users`). A random code the bot
does not know tracks nothing, and the bot's API has no action for campaign codes. So:

* "pool": referrer accounts the advertiser owns; each ad (or group of ads) gets one as its `start`.
  Works today. Real customers' ids are never used (they could be paid commission and get messages).
* "campaign": a short random code per ad (`c_` + 6 characters). Only usable once the bot can report
  each user's start code; until then it is shown disabled with a request for the bot's developer.
"""

import secrets
import string
from dataclasses import dataclass
from typing import Any

ALPHABET = string.ascii_lowercase + string.digits


@dataclass(frozen=True)
class TrackingMode:
    key: str
    label: str
    available: bool
    description: str

    def public(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "available": self.available, "description": self.description}


POOL = TrackingMode(
    "pool",
    "استخر معرف‌ها",
    True,
    "شناسه‌ی عددی حساب‌های معرفی که مال خودتان است؛ هر آگهی (یا گروه آگهی) لینک دعوت یکی از آن‌ها را می‌گیرد.",
)
CAMPAIGN = TrackingMode(
    "campaign",
    "کد کمپین",
    False,
    "برای هر آگهی یک کد کوتاه تصادفی (مثل c_k3x9qa). نیاز به پشتیبانی ربات دارد: ربات باید کد start هر کاربر را "
    "ذخیره کند و از API برگرداند.",
)
MODES = (POOL, CAMPAIGN)

CAMPAIGN_REQUEST = """سلام. برای ردیابی فروش هر آگهی تلگرام، لطفاً این امکان را به API ربات اضافه کنید:
۱) وقتی کاربر جدید با لینک t.me/<ربات>?start=<کد> وارد می‌شود و <کد> شناسه‌ی عددی یک کاربر نیست، همان کد (مثل c_k3x9qa) را در ستونی مثل start_code روی کاربر ذخیره کنید.
۲) در اکشن users → user و در فهرست کاربران، فیلد start_code را برگردانید.
۳) یک اکشن خواندنی (GET) مثل users → users_by_start با ورودی start_code و page/limit اضافه کنید که کاربران آن کد را برگرداند.
کدها فقط حروف کوچک انگلیسی، عدد و _ هستند و حداکثر ۶۴ کاراکترند. ممنون."""


def campaign_code() -> str:
    return "c_" + "".join(secrets.choice(ALPHABET) for _ in range(6))


def mode(key: str) -> TrackingMode:
    return next((m for m in MODES if m.key == key), POOL)
