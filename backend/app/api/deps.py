"""Request dependencies: database session, authentication, CSRF and account lookup."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Forbidden, Unauthorized
from app.core.security import tokens_match
from app.db.session import get_session
from app.models import Account
from app.services import accounts

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "X-CSRF-Token"
CSRF_COOKIE = "tgads_csrf"

Session = Annotated[AsyncSession, Depends(get_session)]


def require_auth(request: Request) -> None:
    """Session cookie must be logged in; state-changing requests must echo the CSRF token."""
    if request.session.get("auth") is not True:
        raise Unauthorized("ابتدا وارد شوید.")
    if request.method not in SAFE_METHODS and not tokens_match(
        request.headers.get(CSRF_HEADER), request.session.get("csrf")
    ):
        raise Forbidden("نشست منقضی شده است؛ صفحه را تازه کنید.", code="csrf_failed")


Auth = Depends(require_auth)


async def get_account(slug: str, s: Session) -> Account:
    return await accounts.by_slug(s, slug)


AccountDep = Annotated[Account, Depends(get_account)]
