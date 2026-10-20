"""Background work inside the web process (run with exactly one worker).

A supervisor wakes every second, reads each account's intervals and starts the syncs that are due
as separate tasks, so a slow bot never delays the Telegram Ads refresh. After a failure the next
attempt backs off exponentially (capped at 15 minutes). Queued Telegram changes run every 5 seconds.
"""

import asyncio
import contextlib
from typing import Any

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.base import now_ts
from app.db.session import session_scope
from app.models import Account
from app.services import actions, sync
from app.services.accounts import settings_of

log = get_logger("scheduler")
KINDS = ("fast", "stats", "bot")
INTERVAL_KEY = {"fast": "sync_fast_seconds", "stats": "sync_stats_seconds", "bot": "sync_bot_seconds"}
MAX_BACKOFF = 900


class Scheduler:
    def __init__(self) -> None:
        self._tasks: dict[tuple[int, str], asyncio.Task[Any]] = {}
        self._loop_task: asyncio.Task[Any] | None = None
        self._jobs_task: asyncio.Task[Any] | None = None
        self._stop = asyncio.Event()
        self._rerun: set[tuple[int, str]] = set()
        self.last_tick = 0

    @property
    def started(self) -> bool:
        return self._loop_task is not None

    def running(self, account_id: int, kind: str) -> bool:
        t = self._tasks.get((account_id, kind))
        return t is not None and not t.done()

    def running_kinds(self, account_id: int) -> list[str]:
        return [k for k in KINDS if self.running(account_id, k)]

    def trigger(self, account_id: int, kind: str, *, force: bool = False) -> bool:
        """Start a sync now unless one is already running. Returns False if it was running.

        With force=True (after a token or key changed) a sync that is already running with the old
        credentials is followed by a fresh one as soon as it finishes.
        """
        if self._loop_task is None:
            return False
        if self.running(account_id, kind):
            if force:
                self._rerun.add((account_id, kind))
            return False
        self._tasks[(account_id, kind)] = asyncio.create_task(
            self._run(account_id, kind), name=f"sync-{account_id}-{kind}"
        )
        return True

    async def _run(self, account_id: int, kind: str) -> None:
        try:
            await sync.run(account_id, kind)
        except sync.SyncSkipped:
            pass
        except Exception as e:  # errors are recorded in sync_state by the sync itself
            log.warning("sync %s for account %s failed: %s", kind, account_id, e)
        finally:
            if (account_id, kind) in self._rerun and not self._stop.is_set():
                self._rerun.discard((account_id, kind))
                self._tasks[(account_id, kind)] = asyncio.create_task(
                    self._run(account_id, kind), name=f"sync-{account_id}-{kind}"
                )

    @staticmethod
    def due(acc: Account, kind: str, now: int) -> bool:
        if kind == "bot":
            if not (acc.bot_base_url and acc.bot_api_key_enc):
                return False
        elif not acc.tg_token_enc:
            return False
        if kind == "stats" and not ((acc.sync_state or {}).get("fast") or {}).get("last_ok"):
            return False  # daily stats need the ad list from a successful fast sync
        st = settings_of(acc)
        interval = int(st[INTERVAL_KEY[kind]])
        state = (acc.sync_state or {}).get(kind) or {}
        last_try = int(state.get("last_try") or 0)
        fails = int(state.get("fails") or 0)
        wait = interval if not fails else min(interval * 2 ** min(fails, 6), max(MAX_BACKOFF, interval))
        return now - last_try >= wait

    async def tick(self) -> None:
        now = now_ts()
        async with session_scope() as s:
            accounts = list((await s.execute(select(Account))).scalars())
            for a in accounts:
                s.expunge(a)
        alive = {a.id for a in accounts}
        for key in [k for k in self._tasks if k[0] not in alive or self._tasks[k].done()]:
            self._tasks.pop(key, None)
        for acc in accounts:
            for kind in KINDS:
                if not self.running(acc.id, kind) and self.due(acc, kind, now):
                    # fast first: stats need the ad list; bot data is independent.
                    if kind == "stats" and self.running(acc.id, "fast"):
                        continue
                    self.trigger(acc.id, kind)
        self.last_tick = now

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:
                log.exception("scheduler tick failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=1)

    async def _jobs(self) -> None:
        while not self._stop.is_set():
            try:
                await actions.process_due()
            except Exception:
                log.exception("job runner failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=5)

    def start(self) -> None:
        self._stop.clear()
        self._loop_task = asyncio.create_task(self._loop(), name="scheduler")
        self._jobs_task = asyncio.create_task(self._jobs(), name="jobs")

    async def stop(self) -> None:
        self._stop.set()
        tasks = [t for t in (self._loop_task, self._jobs_task, *self._tasks.values()) if t is not None]
        for t in tasks:
            if not t.done() and t not in (self._loop_task, self._jobs_task):
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._rerun.clear()
        self._loop_task = self._jobs_task = None


scheduler = Scheduler()
