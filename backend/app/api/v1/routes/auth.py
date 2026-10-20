from fastapi import APIRouter, Request, Response

from app.api.deps import CSRF_COOKIE, Auth, Session
from app.core.config import get_settings
from app.core.errors import AppError, Unauthorized
from app.core.security import login_limiter, new_csrf_token
from app.schemas.requests import LoginIn, PasswordChangeIn
from app.services import app_settings, events

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_csrf(request: Request, response: Response) -> str:
    token = request.session.get("csrf") or new_csrf_token()
    request.session["csrf"] = token
    response.set_cookie(
        CSRF_COOKIE,
        token,
        secure=get_settings().cookie_secure,
        samesite="lax",
        httponly=False,
        max_age=7 * 86400,
        path="/",
    )
    return token


@router.get("/me")
async def me(request: Request, response: Response) -> dict:
    settings = get_settings()
    _set_csrf(request, response)
    return {
        "authenticated": request.session.get("auth") is True,
        "version": settings.app_version,
        "problems": settings.problems(),
        "insecure_cookie": settings.cookie_secure
        and request.url.scheme != "https"
        and request.headers.get("x-forwarded-proto", "") != "https",
    }


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, s: Session) -> dict:
    ip = request.client.host if request.client else "?"
    if get_settings().problems():
        raise AppError("اول تنظیمات سرور (فایل .env) را کامل کنید.", code="not_configured")
    if login_limiter.blocked(ip):
        raise AppError(
            "تلاش‌های ناموفق زیاد بود. ۱۰ دقیقه بعد دوباره امتحان کنید.", code="rate_limited", status_code=429
        )
    if not await app_settings.check_password(s, body.password.get_secret_value()):
        login_limiter.fail(ip)
        raise Unauthorized("رمز اشتباه است.", code="wrong_password")
    login_limiter.reset(ip)
    request.session.clear()
    request.session["auth"] = True
    _set_csrf(request, response)
    events.log(s, "login", actor="user", detail=ip)
    await s.commit()
    return {"authenticated": True}


@router.post("/logout", dependencies=[Auth])
async def logout(request: Request, response: Response) -> dict:
    request.session.clear()
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"authenticated": False}


@router.post("/password", dependencies=[Auth])
async def change_password(body: PasswordChangeIn, s: Session) -> dict:
    await app_settings.change_password(s, body.current.get_secret_value(), body.new.get_secret_value())
    events.log(s, "password_changed", actor="user", level="warn")
    await s.commit()
    return {"ok": True}
