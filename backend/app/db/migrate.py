"""Run Alembic migrations at startup so a container upgrade upgrades the database too."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import BACKEND_DIR, get_settings


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(BACKEND_DIR) / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().sync_database_url)
    return cfg


def upgrade_to_head() -> None:
    command.upgrade(alembic_config(), "head")
