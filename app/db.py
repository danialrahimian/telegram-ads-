"""SQLite storage. One file in DATA_DIR, safe to back up while the app runs."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from . import config

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS account (
  id INTEGER PRIMARY KEY CHECK (id = 1), title TEXT, currency TEXT,
  spent_budget REAL, remaining_budget REAL, ads_budget REAL, synced_at INTEGER);
CREATE TABLE IF NOT EXISTS ads (
  ad_id INTEGER PRIMARY KEY, title TEXT, text TEXT, promote_url TEXT, cpm REAL, placement TEXT,
  status TEXT, is_paused INTEGER, views INTEGER, clicks INTEGER, actions INTEGER, action_type TEXT,
  spent_budget REAL, remaining_budget REAL, created_date INTEGER, target_type TEXT, target_label TEXT,
  target_json TEXT, has_photo INTEGER, has_video INTEGER, show_userpic INTEGER, decline_reason TEXT,
  synced_at INTEGER, gone INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ad_meta (
  ad_id INTEGER PRIMARY KEY, code TEXT, variant_id INTEGER, note TEXT, created_by_app INTEGER DEFAULT 0);
CREATE UNIQUE INDEX IF NOT EXISTS ad_meta_code ON ad_meta(code) WHERE code IS NOT NULL AND code != '';
CREATE TABLE IF NOT EXISTS stats (
  ad_id INTEGER, day TEXT, views INTEGER, clicks INTEGER, actions INTEGER, spent REAL,
  PRIMARY KEY (ad_id, day));
CREATE TABLE IF NOT EXISTS variants (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, text TEXT, active INTEGER DEFAULT 1, created_at INTEGER);
CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at INTEGER, ad_id INTEGER, kind TEXT, amount REAL,
  reason TEXT, metrics TEXT, status TEXT DEFAULT 'pending', decided_at INTEGER, result TEXT);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, ad_id INTEGER, amount REAL, run_at INTEGER,
  status TEXT DEFAULT 'queued', attempts INTEGER DEFAULT 0, result TEXT, proposal_id INTEGER,
  created_at INTEGER, idem_key TEXT);
CREATE TABLE IF NOT EXISTS conversions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT, event TEXT, amount REAL, ext_id TEXT UNIQUE, ts INTEGER);
CREATE INDEX IF NOT EXISTS conversions_code ON conversions(code, event);
CREATE TABLE IF NOT EXISTS log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, actor TEXT, action TEXT, ad_id INTEGER, detail TEXT);
CREATE TABLE IF NOT EXISTS analyses (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, model TEXT, question TEXT, output TEXT);
"""

DEFAULT_SETTINGS = {
    "bot_username": "sychonetbot",
    "target_cost_per_customer": 0.08,
    "min_spend_to_judge": 0.5,
    "stop_cost_per_start": 0.045,
    "scale_cost_per_start": 0.025,
    "stalled_spend_28d": 0.025,
    "stalled_min_remaining": 0.1,
    "stalled_min_age_days": 7,
    "topup_max_per_ad": 1.0,
    "topup_daily_cap": 5.0,
    "fatigue_age_days": 21,
    "fatigue_ratio": 1.5,
    "min_purchases_to_judge": 3,
    "sync_interval_minutes": 60,
    "automation_paused": False,
    "default_cpm_channel": 0.45,
    "default_cpm_bot": 0.5,
    "default_budget": 1.0,
}

DEFAULT_VARIANTS = [
    ("الف: برند و پیشنهاد",
     "سایکونت | VPN نامحدود با ۳۰ سرور اختصاصی در کشورهای مختلف 🌍 اشتراک [مدت] فقط ۵۹ هزار تومان. اول رایگان تستش کن، بعد بخر 👇"),
    ("ب: مشکل مخاطب",
     "از قطعی و کندی خسته شدی؟ سایکونت با ۳۰ سرور اختصاصی وصلت نگه می‌داره. همین الان تست رایگان بگیر؛ اشتراک از ۵۹ هزار تومان 👇"),
    ("ج: تست رایگان",
     "🎁 تست رایگان VPN سایکونت: بدون پرداخت امتحانش کن. ۳۰ سرور اختصاصی، حجم نامحدود، اشتراک از ۵۹ هزار تومان. ربات رو استارت کن 👇"),
]


def now():
    return int(time.time())


def _connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def tx():
    """One transaction. Writes are serialized by a process-wide lock."""
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def query(sql, params=()):
    conn = _connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def init():
    with tx() as c:
        c.executescript(SCHEMA)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, json.dumps(v)))
        if not c.execute("SELECT 1 FROM variants LIMIT 1").fetchone():
            for name, text in DEFAULT_VARIANTS:
                c.execute("INSERT INTO variants(name, text, active, created_at) VALUES (?, ?, 1, ?)", (name, text, now()))


def settings():
    out = dict(DEFAULT_SETTINGS)
    for r in query("SELECT key, value FROM settings"):
        out[r["key"]] = json.loads(r["value"])
    return out


def set_setting(key, value):
    with tx() as c:
        c.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, json.dumps(value)))


def log(actor, action, ad_id=None, detail=""):
    with tx() as c:
        c.execute("INSERT INTO log(ts, actor, action, ad_id, detail) VALUES (?, ?, ?, ?, ?)",
                  (now(), actor, action, ad_id, detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)))
