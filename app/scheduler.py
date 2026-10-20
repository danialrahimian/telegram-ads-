"""Background loop inside the web process: runs due jobs every 15 seconds and syncs on schedule."""
import threading
import traceback

from . import actions, db, rules, sync

RETRY_AFTER_FAILURE = 300  # seconds between attempts while Telegram is unreachable
_stop = threading.Event()
_sync_lock = threading.Lock()


def sync_now(actor="user"):
    if not _sync_lock.acquire(blocking=False):
        return None
    try:
        db.set_setting("last_sync_attempt", db.now())
        res = sync.run(log_actor=actor)
        rules.generate()
        return res
    finally:
        _sync_lock.release()


def sync_running():
    return _sync_lock.locked()


def _loop():
    while not _stop.is_set():
        try:
            actions.process_due()
            s = db.settings()
            last = (s.get("last_sync") or {}).get("at") or 0
            attempt = s.get("last_sync_attempt") or 0
            due = db.now() - last >= int(s.get("sync_interval_minutes") or 60) * 60
            if due and db.now() - attempt >= RETRY_AFTER_FAILURE:
                sync_now("scheduler")
            db.set_setting("last_loop", {"at": db.now(), "error": None})
        except Exception as e:
            db.set_setting("last_loop", {"at": db.now(), "error": f"{e}"})
            traceback.print_exc()
        _stop.wait(15)


def start():
    t = threading.Thread(target=_loop, name="scheduler", daemon=True)
    t.start()
    return t


def stop():
    _stop.set()
