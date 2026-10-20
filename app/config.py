"""Settings that come from the environment (.env). Secrets live only here, never in the database."""
import os
from pathlib import Path


def _load_dotenv():
    path = Path(os.environ.get("ENV_FILE", Path(__file__).resolve().parent.parent / ".env"))
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if value[:1] in ('"', "'") and value[-1:] == value[:1] and len(value) > 1:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key.strip(), value)


_load_dotenv()

APP_VERSION = os.environ.get("APP_VERSION", "dev")
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR.parent / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.db"

TG_ADS_TOKEN = os.environ.get("TG_ADS_TOKEN", "")
TG_ADS_API_BASE = os.environ.get("TG_ADS_API_BASE", "https://promoteapi.telegram.org")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
CONVERSIONS_SECRET = os.environ.get("CONVERSIONS_SECRET", "")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")

# Telegram requires an ad to be inactive for 10 minutes before its budget can be withdrawn.
WITHDRAW_DELAY_SECONDS = int(os.environ.get("WITHDRAW_DELAY_SECONDS", "660"))
# Set to 0 to disable the background scheduler (used in tests).
SCHEDULER_ENABLED = os.environ.get("SCHEDULER_ENABLED", "1") == "1"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") == "1"


def problems():
    """Configuration errors to show on the login page instead of starting half-configured."""
    out = []
    if not TG_ADS_TOKEN:
        out.append("TG_ADS_TOKEN تنظیم نشده است.")
    if len(ADMIN_PASSWORD) < 10:
        out.append("ADMIN_PASSWORD باید دست‌کم ۱۰ کاراکتر باشد.")
    if len(SESSION_SECRET) < 32:
        out.append("SESSION_SECRET باید دست‌کم ۳۲ کاراکتر تصادفی باشد.")
    return out
