from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import now_ts
from app.models import Event


def log(
    s: AsyncSession,
    action: str,
    *,
    account_id: int | None = None,
    actor: str = "system",
    ad_id: int | None = None,
    detail: str = "",
    level: str = "info",
) -> None:
    """Add an activity-log row to the session; the caller's commit saves it."""
    s.add(
        Event(
            ts=now_ts(),
            account_id=account_id,
            actor=actor,
            action=action,
            ad_id=ad_id,
            level=level,
            detail=detail[:2000],
        )
    )
