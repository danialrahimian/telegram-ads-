"""Sales-bot connection diagnostics: every request the panel needs, tried separately, explained in Persian.

Each row says what was sent (method, path, action, body — never the key), what came back (HTTP status,
time, the bot's `msg`, the first words of a non-JSON answer, rows and field names) and a cause with a
fix. The report can be copied as plain text for the bot's developer; secrets are scrubbed everywhere.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.config import get_settings
from app.core.errors import AppError
from app.db.base import now_ts
from app.integrations.bot_api import BotApiClient, BotApiError, scrub
from app.models import Account, ReferralTag
from app.services import app_settings, events
from app.services.accounts import settings_of

SECTION_PERMISSION = {
    "/api/statbot": "statbot",
    "/api/users": "users",
    "/api/settings": "settings",
    "/api/invoice": "invoice",
}
IDENTITY_KEYS = ("username", "bot_username", "usernamebot", "username_bot", "botname", "bot_name", "id_bot", "bot_id")


def classify(entry: dict[str, Any], *, expect_rows: bool = False) -> dict[str, str]:
    """Cause of one traced request: {code, title, fix}."""
    status = entry.get("http_status")
    kind = entry.get("error_kind") or ""
    msg = (entry.get("msg") or "").strip()
    low = msg.lower()
    path = entry.get("path") or ""

    def r(code: str, title: str, fix: str) -> dict[str, str]:
        return {"code": code, "title": title, "fix": fix}

    if kind == "dns":
        return r(
            "dns", "نام دامنه پیدا نشد (DNS)", "آدرس ربات را بررسی کنید؛ دامنه وجود ندارد یا از سرور پنل قابل حل نیست."
        )
    if kind == "tls":
        return r(
            "tls",
            "خطای TLS / گواهی",
            "گواهی HTTPS ربات نامعتبر یا منقضی است؛ گواهی را تمدید کنید یا آدرس درست را بدهید.",
        )
    if kind == "timeout":
        return r("timeout", "مهلت پاسخ تمام شد", "ربات در ۳۰ ثانیه جواب نداد؛ سرور ربات کند یا خاموش است.")
    if kind:
        return r("connect", "اتصال برقرار نشد", "سرور ربات در دسترس نیست (پورت بسته، فایروال یا سرور خاموش).")
    ctype = (entry.get("content_type") or "").lower()
    redirected = entry.get("redirected_to") or ""
    if redirected and ("login" in redirected.lower() or "html" in ctype):
        return r(
            "redirect",
            "ریدایرکت به صفحه‌ی لاگین/HTML",
            f"درخواست به {redirected} رفت؛ آدرس API اشتباه است یا پشت لاگین است.",
        )
    if status == 404:
        return r(
            "not_found",
            "آدرس اشتباه (HTTP 404)",
            "این مسیر روی سرور نیست؛ آدرس پایه‌ی API ربات را بررسی کنید (آدرس docs هم قبول است).",
        )
    if status == 401 or (status == 403 and ("token" in low or "invalid" in low)):
        return r(
            "auth",
            "کلید API نامعتبر (HTTP " + str(status) + ")",
            "کلید را دوباره از پنل ربات کپی کنید؛ کلید این ربات با ربات دیگر فرق دارد.",
        )
    if status == 403 or "access denied" in low:
        perm = SECTION_PERMISSION.get(path, path)
        return r(
            "access_denied",
            f"دسترسی «{perm}» به کلید داده نشده",
            f"در پنل ربات، دسترسی بخش {perm} را به این کلید API بدهید.",
        )
    if status == 405 or "method invalid" in low or "method not allowed" in low:
        return r(
            "method",
            "متد HTTP اشتباه (405)",
            "ربات این اکشن را با این متد قبول نمی‌کند؛ مستندات نسخه‌ی ربات را با توسعه‌دهنده چک کنید.",
        )
    if status == 429:
        return r("rate_limited", "محدودیت تعداد درخواست (429)", "فاصله‌ی همگام‌سازی ربات را بیشتر کنید.")
    if status is not None and status >= 500:
        detail = entry.get("excerpt") or msg or f"HTTP {status}"
        return r(
            "server_error",
            f"خطای داخلی ربات (HTTP {status})",
            f"خطا در سرور ربات رخ می‌دهد: «{detail[:160]}». این گزارش را برای توسعه‌دهنده‌ی ربات بفرستید.",
        )
    if status is not None and status >= 400:
        return r("http_error", f"HTTP {status}", msg or "پاسخ خطا از ربات.")
    if entry.get("empty"):
        return r("empty", "پاسخ خالی", "ربات بدنه‌ای برنگرداند؛ احتمالاً خطای PHP پنهان شده است.")
    if not entry.get("json"):
        if "html" in ctype or redirected:
            return r("html", "پاسخ HTML به جای JSON", "آدرس به صفحه‌ی وب (نه API) می‌رسد؛ آدرس پایه را بررسی کنید.")
        return r("not_json", "پاسخ JSON نیست", f"ربات متن غیر JSON برگرداند: «{(entry.get('excerpt') or '')[:120]}»")
    if entry.get("envelope_ok") is False:
        if "action" in low and "invalid" in low:
            return r(
                "bad_action",
                "اکشن ناشناخته",
                f"ربات اکشن «{entry.get('action')}» را نمی‌شناسد (پیام: {msg}). نسخه‌ی ربات این درخواست را ندارد.",
            )
        return r("bot_error", "ربات خطا برگرداند", f"پیام ربات: «{msg}»")
    if expect_rows:
        if entry.get("rows") == 0 and entry.get("obj_type") not in ("list", "dict", "NoneType"):
            return r(
                "unknown_shape",
                "ساختار پاسخ ناشناخته",
                "پاسخ موفق بود ولی فهرستی در آن پیدا نشد؛ نام فیلدها را برای بررسی ببینید.",
            )
        if entry.get("rows") == 0:
            return r(
                "ok_empty",
                "درخواست موفق، ولی صفر ردیف",
                "درخواست کار می‌کند ولی داده‌ای برنگشت؛ فیلترهای ارسالی و نوع‌های خرید را بررسی کنید.",
            )
    return r("ok", "سالم", "")


def _row(name: str, label: str, entry: dict[str, Any], *, expect_rows: bool, error: str = "") -> dict[str, Any]:
    cause = classify(entry, expect_rows=expect_rows)
    return {
        "name": name,
        "label": label,
        "method": entry.get("method"),
        "path": entry.get("path"),
        "action": entry.get("action"),
        "body": entry.get("body") or {},
        "http_status": entry.get("http_status"),
        "elapsed_ms": entry.get("elapsed_ms"),
        "msg": entry.get("msg") or "",
        "excerpt": entry.get("excerpt") or "",
        "rows": entry.get("rows"),
        "fields": entry.get("fields") or [],
        "ok": cause["code"] in ("ok", "ok_empty"),
        "cause": cause,
        "error": error,
    }


def users_jump(prev: int | None, cur: int | None) -> bool:
    """A sudden large change of the bot's user count: probably another bot or key was connected."""
    if not prev or cur is None:
        return False
    if cur < prev * 0.5 and prev - cur > 20:
        return True
    return cur - prev > max(500, prev // 2)


def _identity(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    stack: list[Any] = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if str(k).lower() in IDENTITY_KEYS and isinstance(v, str | int) and str(v).strip():
                    return str(v).strip().lstrip("@")
                if isinstance(v, dict | list):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur[:20])
    return ""


async def diagnose(s: AsyncSession, acc: Account) -> dict[str, Any]:
    key = crypto.decrypt(acc.bot_api_key_enc)
    if not acc.bot_base_url or not key:
        raise AppError("آدرس و کلید API ربات برای این حساب وارد نشده است.", code="bot_not_configured")
    st = settings_of(acc)
    rows: list[dict[str, Any]] = []
    now = now_ts()
    referrers = [str(x) for x in st.get("referrer_pool") or []]
    for (rid,) in await s.execute(select(ReferralTag.referrer_id).where(ReferralTag.account_id == acc.id)):
        if str(rid) not in referrers:
            referrers.append(str(rid))
    referrers = referrers[:10]
    stats: dict[str, Any] | None = None
    setting_obj: Any = None
    async with BotApiClient(acc.bot_base_url, key) as c:

        async def probe(
            name: str, label: str, method: str, path: str, action: str | None, expect_rows: bool, **body: Any
        ) -> Any:
            err = ""
            obj: Any = None
            try:
                obj = await c.request(method, path, action, **body)
            except BotApiError as e:
                err = e.friendly
            rows.append(_row(name, label, c.trace[-1], expect_rows=expect_rows, error=err))
            return obj

        obj = await probe("statbot", "آمار ربات (statbot)", "GET", "/api/statbot", None, False)
        if isinstance(obj, dict):
            stats = obj
        shapes: list[tuple[str, str, dict[str, Any]]] = [
            ("plain", "صفحه‌بندی ساده", {"page": 1, "limit": 5}),
            ("bounded", "با بازه‌ی زمانی", {"page": 1, "limit": 5, "from": 1, "to": now + 86400}),
            ("empty_filters", "با فیلترهای خالی", {"page": 1, "limit": 5, "q": "", "type": "", "source": ""}),
            ("unpaged", "بدون صفحه‌بندی", {}),
        ]
        tx_ok = False
        for shape, label, body in shapes:
            await probe(
                f"transactions:{shape}", f"تراکنش‌ها — {label}", "GET", "/api/users", "transactions", True, **body
            )
            tx_ok = tx_ok or rows[-1]["ok"]
        for ptype in [str(t) for t in st.get("purchase_types") or [] if str(t)][:5]:
            await probe(
                f"transactions:type:{ptype}",
                f"تراکنش‌ها — بر اساس نوع خرید «{ptype}»",
                "GET",
                "/api/users",
                "transactions",
                True,
                page=1,
                limit=5,
                type=ptype,
            )
            tx_ok = tx_ok or rows[-1]["ok"]
        for rid in referrers:
            await probe(
                f"affiliates:{rid}",
                f"دعوت‌شده‌های معرف {rid} (affiliates_users)",
                "GET",
                "/api/users",
                "affiliates_users",
                True,
                chat_id=rid,
                page=1,
                limit=1000,
            )
        if referrers:
            await probe(
                f"user:{referrers[0]}",
                f"اطلاعات کاربر {referrers[0]} (user)",
                "GET",
                "/api/users",
                "user",
                False,
                chat_id=referrers[0],
            )
        setting_obj = await probe(
            "settings", "تنظیمات ربات (setting_info)", "GET", "/api/settings", "setting_info", False
        )
        if not tx_ok:
            await probe(
                "invoices", "سرویس‌ها (invoice → invoices)", "GET", "/api/invoice", "invoices", True, page=1, limit=5
            )

    warnings: list[str] = []
    count_user = None
    if stats:
        try:
            count_user = int(str(stats.get("count_user")))
        except (TypeError, ValueError):
            count_user = None
    reported = _identity(setting_obj)
    configured = (acc.bot_username or "").lstrip("@")
    if reported and configured and reported.lower() != configured.lower() and not reported.isdigit():
        warnings.append(
            f"ربات می‌گوید نامش «{reported}» است ولی نام کاربری واردشده «{configured}» است؛ "
            "احتمالاً کلید یا آدرس ربات دیگری وارد شده."
        )
    state = dict(acc.sync_state or {})
    prev = state.get("bot_users_last")
    if users_jump(prev if isinstance(prev, int) else None, count_user):
        warnings.append(
            f"تعداد کاربران ربات ناگهان از {prev} به {count_user} رسید؛ احتمالاً ربات یا کلید دیگری وصل شده است."
        )
    secrets = [key, crypto.decrypt(acc.tg_token_enc) or "", await app_settings.claude_key(s) or ""]
    report = scrub(
        {
            "ts": now,
            "version": get_settings().app_version,
            "base_url": acc.bot_base_url,
            "username": configured,
            "rows": rows,
            "identity": {"count_user": count_user, "reported_username": reported, "configured_username": configured},
            "warnings": warnings,
            "ok": sum(1 for r in rows if r["ok"]),
            "failed": sum(1 for r in rows if not r["ok"]),
        },
        secrets,
    )
    if count_user is not None:
        state["bot_users_last"] = count_user
    state["bot_diag"] = report
    acc.sync_state = state
    if report["failed"]:
        events.log(
            s,
            "bot_diagnose",
            account_id=acc.id,
            actor="user",
            level="warn",
            detail=f"{report['failed']} درخواست ناموفق",
        )
    return report


def report_text(report: dict[str, Any], secrets: list[str] | tuple[str, ...] = ()) -> str:
    """Plain-text summary for the bot developer (Persian labels, raw technical details)."""
    ts = datetime.fromtimestamp(int(report.get("ts") or 0), UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        "گزارش عیب‌یابی اتصال به API ربات (Telegram Ads Manager)",
        f"نسخه‌ی پنل: {report.get('version')}",
        f"زمان: {ts}",
        f"آدرس پایه: {report.get('base_url')}",
        f"نام کاربری ربات در پنل: @{report.get('username') or '—'}",
        f"کاربران (statbot): {report.get('identity', {}).get('count_user')}",
        "کلید API در این گزارش نیست (در هدر Token فرستاده می‌شود).",
        "",
    ]
    for w in report.get("warnings") or []:
        lines.append(f"⚠ {w}")
    for i, r in enumerate(report.get("rows") or [], 1):
        lines.append(f"{i}. {r['label']} — {'OK' if r['ok'] else 'FAILED'}: {r['cause']['title']}")
        lines.append(f"   {r['method']} {r['path']}" + (f"  actions={r['action']}" if r.get("action") else ""))
        if r.get("body"):
            lines.append(f"   body: {r['body']}")
        lines.append(
            f"   HTTP {r.get('http_status') if r.get('http_status') is not None else '—'} · {r.get('elapsed_ms')} ms"
        )
        if r.get("msg"):
            lines.append(f"   msg: {r['msg']}")
        if r.get("excerpt"):
            lines.append(f"   پاسخ: {r['excerpt'][:300]}")
        if r.get("rows") is not None:
            lines.append(
                f"   ردیف‌ها: {r['rows']}" + (f" · فیلدها: {', '.join(r['fields'][:25])}" if r.get("fields") else "")
            )
        if r["cause"].get("fix") and not r["ok"]:
            lines.append(f"   راه‌حل: {r['cause']['fix']}")
    return str(scrub("\n".join(lines), list(secrets)))
