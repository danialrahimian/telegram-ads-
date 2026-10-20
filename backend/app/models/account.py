from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class Account(Base):
    """One Telegram Ads advertiser account together with the sales bot it promotes."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    color: Mapped[str] = mapped_column(String(16), default="teal")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    # Telegram Ads connection
    tg_token_enc: Mapped[str | None] = mapped_column(Text)
    tg_token_last4: Mapped[str] = mapped_column(String(8), default="")
    tg_account_id: Mapped[str] = mapped_column(String(120), default="")
    tg_title: Mapped[str] = mapped_column(String(200), default="")
    currency: Mapped[str] = mapped_column(String(8), default="")
    spent_budget: Mapped[float] = mapped_column(Float, default=0)
    remaining_budget: Mapped[float] = mapped_column(Float, default=0)
    ads_budget: Mapped[float] = mapped_column(Float, default=0)
    tg_status: Mapped[str] = mapped_column(String(16), default="unset")  # unset | ok | error
    tg_error: Mapped[str] = mapped_column(Text, default="")
    tg_checked_ts: Mapped[int] = mapped_column(Integer, default=0)

    # Sales bot connection
    bot_base_url: Mapped[str] = mapped_column(String(300), default="")
    bot_username: Mapped[str] = mapped_column(String(64), default="")
    bot_api_key_enc: Mapped[str | None] = mapped_column(Text)
    bot_key_last4: Mapped[str] = mapped_column(String(8), default="")
    bot_status: Mapped[str] = mapped_column(String(16), default="unset")
    bot_error: Mapped[str] = mapped_column(Text, default="")
    bot_checked_ts: Mapped[int] = mapped_column(Integer, default=0)
    bot_stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    bot_fields: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # detected response fields
    last_tx_ts: Mapped[int] = mapped_column(Integer, default=0)

    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    sync_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    automation_paused: Mapped[bool] = mapped_column(Boolean, default=False)


class AccountSnapshot(Base):
    """Totals captured on every fast sync; powers the intraday 'live' chart."""

    __tablename__ = "account_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    ts: Mapped[int] = mapped_column(Integer, index=True)
    spent_budget: Mapped[float] = mapped_column(Float, default=0)
    remaining_budget: Mapped[float] = mapped_column(Float, default=0)
    ads_budget: Mapped[float] = mapped_column(Float, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    actions: Mapped[int] = mapped_column(Integer, default=0)
    bot_users: Mapped[int | None] = mapped_column(Integer)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
