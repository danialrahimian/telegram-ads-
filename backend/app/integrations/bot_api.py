"""Client for the sales bot's admin API ("VPN Bot — Admin API", Mirza-style).

Facts from the bot's OpenAPI document:
  * Auth: header `Token: <bot token or API key>`. A key without permission gets HTTP 403 "access denied".
  * Every endpoint is one path that dispatches on `actions` in a JSON body; the HTTP method is
    enforced per action (reads are GET *with* a JSON body).
  * Responses are `{status, msg, obj}` except `/api/statbot`, which returns a flat object.

The document does not describe the shape of `obj` for user lists and the transaction ledger,
so the normalizers below accept the common field names and the panel shows which fields
were actually found.
"""

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

LIST_KEYS = ("transactions", "users", "affiliates", "list", "items", "data", "rows", "records", "result", "obj")
USER_ID_KEYS = ("id", "chat_id", "id_user", "user_id", "userid", "from_id")
REGISTER_KEYS = ("register", "registered", "register_time", "join_date", "created_at", "date", "time")
TX_ID_KEYS = ("id", "id_transaction", "transaction_id", "tx_id", "id_order", "order_id")
TX_USER_KEYS = ("id_user", "user_id", "chat_id", "userid", "id_from", "from_id")
TX_TYPE_KEYS = ("type", "action", "event", "kind")
TX_AMOUNT_KEYS = ("amount", "price", "value", "sum", "total")
TX_TIME_KEYS = ("created_at", "time", "date", "timestamp", "created", "time_sell")


class BotApiError(Exception):
    def __init__(self, message: str, *, http_status: int | None = None, path: str = "", action: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status
        self.path = path
        self.action = action

    @property
    def forbidden(self) -> bool:
        return self.http_status == 403 or "access denied" in self.message.lower()

    @property
    def friendly(self) -> str:
        where = f"{self.path} ({self.action})" if self.action else self.path
        if self.http_status == 403 and "token" in self.message.lower():
            return "کلید API ربات نامعتبر است."
        if self.forbidden:
            return f"کلید API به {where} دسترسی ندارد. در ربات، دسترسی این بخش را به کلید بدهید."
        if self.http_status is None:
            return f"اتصال به ربات برقرار نشد ({self.message})."
        if self.http_status >= 500:
            return (
                f"{where}: خطای داخلی خودِ ربات ({self.message}). این خطا در سرور ربات رخ می‌دهد؛ "
                "متن آن را برای توسعه‌دهنده‌ی ربات بفرستید."
            )
        return f"{where}: {self.message}"


def normalize_base_url(url: str) -> str:
    """Accept what people paste (…/api/docs, trailing slashes) and return scheme://host[:port][/prefix]."""
    url = url.strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError("آدرس ربات معتبر نیست")
    path = p.path.rstrip("/")
    for suffix in ("/api/docs", "/docs", "/api"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return f"{p.scheme}://{p.netloc}{path}"


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    lower = {str(k).lower(): v for k, v in row.items()}
    for k in keys:
        v = lower.get(k.lower())
        if v not in (None, ""):
            return v
    return None


def extract_rows(obj: Any) -> list[dict[str, Any]]:
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)]
    if isinstance(obj, dict):
        for k in LIST_KEYS:
            v = obj.get(k)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
            if isinstance(v, dict):
                nested = extract_rows(v)
                if nested:
                    return nested
        for v in obj.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


def to_ts(value: Any, tz: ZoneInfo | None = None) -> int:
    """Unix seconds from ints (s or ms), digit strings or 'YYYY-MM-DD HH:MM:SS'-like strings."""
    if value in (None, "", 0, "0"):
        return 0
    if isinstance(value, int | float):
        v = int(value)
        return v // 1000 if v > 10**12 else v
    s = str(value).strip()
    if s.isdigit():
        return to_ts(int(s), tz)
    s = s.replace("/", "-").replace("T", " ").rstrip("Z")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
        return int(dt.replace(tzinfo=tz or UTC).timestamp())
    return 0


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _int(v: Any) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return 0


def _float(v: Any) -> float:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def norm_user(row: dict[str, Any], tz: ZoneInfo | None = None) -> dict[str, Any]:
    return {"user_id": _int(_first(row, USER_ID_KEYS)), "registered_ts": to_ts(_first(row, REGISTER_KEYS), tz)}


def norm_transaction(row: dict[str, Any], tz: ZoneInfo | None = None) -> dict[str, Any]:
    ext = _first(row, TX_ID_KEYS)
    if ext is None:  # no id column: a stable hash of the row keeps re-syncs idempotent
        ext = "h" + hashlib.sha1(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:24]  # noqa: S324
    return {
        "ext_id": str(ext)[:80],
        "user_id": _int(_first(row, TX_USER_KEYS)),
        "type": str(_first(row, TX_TYPE_KEYS) or "")[:40],
        "source": str(row.get("source") or "")[:40],
        "amount": _float(_first(row, TX_AMOUNT_KEYS)),
        "created_ts": to_ts(_first(row, TX_TIME_KEYS), tz),
    }


def body_excerpt(text: str, limit: int = 180) -> str:
    """First readable words of a non-JSON error page (tags and the API key never included)."""
    clean = re.sub(r"<[^>]+>", " ", text or "")
    clean = re.sub(r"\s+", " ", clean).strip()
    clean = re.sub(r"\s+([:.,;])", r"\1", clean)
    return clean[:limit]


# Request shapes tried for the transaction ledger, in order. Customised bot builds sometimes crash
# (HTTP 500) when an optional filter is missing; the first shape that works is remembered per bot.
TX_SHAPES: tuple[str, ...] = ("plain", "bounded", "empty_filters", "unpaged")
_tx_shape: dict[str, str] = {}


def retryable(e: BotApiError) -> bool:
    """Only a crash on the bot side is worth another request shape; auth and validation errors are final."""
    return (e.http_status or 0) >= 500


def field_names(rows: list[dict[str, Any]]) -> list[str]:
    return sorted({str(k) for r in rows[:20] for k in r})


class BotApiClient:
    def __init__(self, base_url: str, api_key: str, *, http: httpx.AsyncClient | None = None) -> None:
        self.base = normalize_base_url(base_url)
        self.api_key = api_key
        self._http = http
        self._own_http = http is None

    async def __aenter__(self) -> "BotApiClient":
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), follow_redirects=True)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._own_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), follow_redirects=True)
        return self._http

    async def request(self, method: str, path: str, actions: str | None = None, **params: Any) -> Any:
        body: dict[str, Any] = dict(params)
        if actions:
            body["actions"] = actions
        url = f"{self.base}{path}"
        headers = {"Token": self.api_key, "Accept": "application/json"}
        try:
            resp = await self.http.request(method, url, headers=headers, json=body)
        except httpx.HTTPError as e:
            raise BotApiError(e.__class__.__name__, path=path, action=actions or "") from e
        try:
            data = resp.json()
        except ValueError:
            # PHP errors come back as HTML/text; a short excerpt tells the bot developer what broke.
            snippet = body_excerpt(resp.text)
            msg = f"HTTP {resp.status_code}" + (f" — {snippet}" if snippet else "")
            raise BotApiError(msg, http_status=resp.status_code, path=path, action=actions or "") from None
        if resp.status_code >= 400:
            msg = str(data.get("msg") if isinstance(data, dict) else "") or f"HTTP {resp.status_code}"
            raise BotApiError(msg, http_status=resp.status_code, path=path, action=actions or "")
        if isinstance(data, dict) and isinstance(data.get("status"), bool):  # the {status, msg, obj} envelope
            if data["status"] is False:
                raise BotApiError(
                    str(data.get("msg") or "error"), http_status=resp.status_code, path=path, action=actions or ""
                )
            return data.get("obj")
        return data

    async def statbot(self) -> dict[str, Any]:
        data = await self.request("GET", "/api/statbot")
        if not isinstance(data, dict):
            raise BotApiError("unexpected response", path="/api/statbot")
        return {k: _int(v) for k, v in data.items() if k.startswith("count_")}

    async def transactions(
        self,
        *,
        page: int = 1,
        limit: int = 500,
        from_ts: int | None = None,
        to_ts_: int | None = None,
        tx_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """One page of the wallet ledger (`users` → `transactions`), newest first."""
        known = _tx_shape.get(self.base)
        order = ([known] if known else []) + [x for x in TX_SHAPES if x != known]
        first_error: BotApiError | None = None
        for shape in order:
            body: dict[str, Any] = {}
            if shape != "unpaged":
                body.update(page=page, limit=limit)
            elif page > 1:
                return []  # without paging the whole ledger came on page 1
            if shape == "empty_filters":
                body.update(q="", type="", source="")
            if from_ts:
                body["from"] = int(from_ts)
            if to_ts_:
                body["to"] = int(to_ts_)
            if shape == "bounded":
                body.setdefault("from", 1)
                body.setdefault("to", int(datetime.now(UTC).timestamp()) + 86400)
            if tx_type:
                body["type"] = tx_type
            try:
                obj = await self.request("GET", "/api/users", "transactions", **body)
            except BotApiError as e:
                if not retryable(e):
                    raise
                first_error = first_error or e
                continue
            _tx_shape[self.base] = shape
            return extract_rows(obj)
        assert first_error is not None
        raise first_error

    async def affiliates(self, chat_id: str, *, page: int = 1, limit: int = 1000) -> list[dict[str, Any]]:
        obj = await self.request("GET", "/api/users", "affiliates_users", chat_id=str(chat_id), page=page, limit=limit)
        return extract_rows(obj)

    async def user(self, chat_id: str) -> Any:
        return await self.request("GET", "/api/users", "user", chat_id=str(chat_id))
