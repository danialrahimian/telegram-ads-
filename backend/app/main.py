"""Telegram Ads Manager: FastAPI app serving the JSON API and the built React app."""

import asyncio
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import Scope

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import get_logger, setup_logging
from app.db.migrate import upgrade_to_head
from app.db.session import dispose_engine, session_scope
from app.services import accounts, app_settings
from app.workers.scheduler import scheduler

log = get_logger("app")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    await asyncio.to_thread(upgrade_to_head)
    async with session_scope() as s:
        await app_settings.sync_env_password(s)
        if not settings.problems():
            await accounts.import_legacy_token(s)
    if settings.scheduler_enabled and not settings.problems():
        scheduler.start()
    log.info("started %s %s", settings.app_name, settings.app_version)
    yield
    await scheduler.stop()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/api/v1/openapi.json",
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value() or secrets.token_hex(32),
        session_cookie="tgads_session",
        max_age=7 * 86400,
        same_site="lax",
        https_only=settings.cookie_secure,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        resp: Response = await call_next(request)
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; form-action 'self'",
        )
        if request.url.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    register_error_handlers(app)
    app.include_router(api_router)

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict:
        return {"ok": True, "version": settings.app_version}

    mount_spa(app, settings.frontend_dist)
    return app


class ImmutableStaticFiles(StaticFiles):
    """Vite puts a content hash in every asset name, so browsers may cache them for a year."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def mount_spa(app: FastAPI, dist: Path) -> None:
    """Serve the built frontend; unknown non-API paths get index.html (client-side routing)."""
    root = dist.resolve()
    index = root / "index.html"
    if (dist / "assets").is_dir():
        app.mount("/assets", ImmutableStaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        if path.startswith("api/"):
            return JSONResponse({"status": 404, "code": "not_found", "detail": "مسیر پیدا نشد."}, status_code=404)
        candidate = (root / path).resolve()
        if path and root in candidate.parents and await asyncio.to_thread(candidate.is_file):
            return FileResponse(candidate)
        if await asyncio.to_thread(index.is_file):
            return FileResponse(index, headers={"Cache-Control": "no-cache"})
        return JSONResponse({"detail": "frontend not built: run `pnpm build` in frontend/"}, status_code=503)


app = create_app()
