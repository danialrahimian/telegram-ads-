"""Telegram Ads API client (https://promoteapi.telegram.org)."""
import json
import time
import uuid
from decimal import Decimal, ROUND_DOWN

import httpx

from . import config

READ_METHODS = {"getCurrentAccount", "getAdsList", "getAdsById", "getAdStats", "getTargetChannel",
                "getTargetBot", "getAccountStats", "getAdTransactionsList"}


class TgAdsError(Exception):
    def __init__(self, method, error):
        super().__init__(f"{method}: {error}")
        self.method = method
        self.error = error


def floor_amount(x, places="0.00001"):
    """Round down to the API's amount precision so we never ask for more than exists."""
    return float(Decimal(str(x)).quantize(Decimal(places), rounding=ROUND_DOWN))


class Client:
    def __init__(self, token=None, base=None, timeout=60):
        self.token = token or config.TG_ADS_TOKEN
        self.base = (base or config.TG_ADS_API_BASE).rstrip("/")
        self.http = httpx.Client(timeout=timeout)

    def call(self, method, idempotency_key=None, files=None, **params):
        headers = {"Authorization": f"Bearer {self.token}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        retries = 3 if (method in READ_METHODS or idempotency_key) else 1
        last = None
        for attempt in range(retries):
            try:
                if files:
                    data = {k: (json.dumps(v) if isinstance(v, (list, dict, bool)) else str(v)) for k, v in params.items()}
                    resp = self.http.post(f"{self.base}/{method}", headers=headers, data=data, files=files)
                else:
                    resp = self.http.post(f"{self.base}/{method}", headers=headers, json=params)
                try:
                    body = resp.json()
                except ValueError:
                    raise TgAdsError(method, f"HTTP {resp.status_code}")
                if body.get("ok"):
                    return body.get("result")
                err = body.get("error", "unknown error")
                if err == "IDEMPOTENT_REQUEST_IN_PROGRESS" and attempt + 1 < retries:
                    time.sleep(2)
                    continue
                raise TgAdsError(method, err)
            except httpx.HTTPError as e:
                last = e
                if attempt + 1 < retries:
                    time.sleep(2 * (attempt + 1))
        raise TgAdsError(method, f"network error: {last}")

    # Reads
    def account(self):
        return self.call("getCurrentAccount")

    def ads(self):
        out, offset = [], None
        while True:
            p = {"limit": 100, "return_target": True}
            if offset:
                p["offset"] = offset
            page = self.call("getAdsList", **p)
            out.extend(page.get("ads", []))
            offset = page.get("next_offset")
            if not offset:
                return out

    def ads_by_id(self, ids):
        out = {}
        for i in range(0, len(ids), 100):
            for ad in self.call("getAdsById", ad_ids=list(ids[i:i + 100])):
                out[ad["ad_id"]] = ad
        return out

    def ad_stats_daily(self, ad_id, from_time, to_time):
        return self.call("getAdStats", ad_id=ad_id, from_time=from_time, to_time=to_time, interval=86400)

    def target_channel(self, username):
        return self.call("getTargetChannel", channel_id=username)

    def target_bot(self, username):
        return self.call("getTargetBot", bot_id=username)

    # Writes (each gets an idempotency key so a retry can never double-spend)
    def pause(self, ad_id, paused=True):
        return self.call("editAd", ad_id=ad_id, is_paused=paused)

    def withdraw(self, ad_id, amount, key=None):
        return self.call("decreaseAdBudget", idempotency_key=key or str(uuid.uuid4()),
                         ad_id=ad_id, amount=floor_amount(amount))

    def topup(self, ad_id, amount, key=None):
        return self.call("increaseAdBudget", idempotency_key=key or str(uuid.uuid4()),
                         ad_id=ad_id, amount=floor_amount(amount))

    def upload_photo(self, filename, content, content_type):
        return self.call("uploadAdPhoto", files={"file": (filename, content, content_type)})

    def create_ad(self, key=None, **params):
        return self.call("createAd", idempotency_key=key or str(uuid.uuid4()), **params)


def client():
    return Client()
