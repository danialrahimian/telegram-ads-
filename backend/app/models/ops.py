from typing import Any

from sqlalchemy import JSON, BigInteger, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Proposal(Base):
    """A change the rules suggest. Nothing happens on Telegram until it is approved."""

    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    created_ts: Mapped[int] = mapped_column(Integer, default=0)
    ad_id: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(16))  # withdraw | stop | topup | refresh
    amount: Mapped[float] = mapped_column(Float, default=0)
    reason: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    decided_ts: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str] = mapped_column(Text, default="")


class Job(Base):
    """A queued change on Telegram (pause, resume, withdraw, top-up)."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    ad_id: Mapped[int] = mapped_column(BigInteger)
    amount: Mapped[float | None] = mapped_column(Float)
    run_at: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    result: Mapped[str] = mapped_column(Text, default="")
    proposal_id: Mapped[int | None] = mapped_column(Integer)
    created_ts: Mapped[int] = mapped_column(Integer, default=0)
    idem_key: Mapped[str] = mapped_column(String(64), default="")
    bulk_item_id: Mapped[int | None] = mapped_column(Integer, index=True)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class BulkOperation(Base):
    """One user-confirmed change applied to many ads (new text/photo, referral links, replacements)."""

    __tablename__ = "bulk_operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # content | referral | replace
    mode: Mapped[str] = mapped_column(String(16), default="replace")  # replace | inplace
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="running", index=True)  # running | stopped | done
    total: Mapped[int] = mapped_column(Integer, default=0)
    created_ts: Mapped[int] = mapped_column(Integer, default=0)
    updated_ts: Mapped[int] = mapped_column(Integer, default=0)
    last_batch_ts: Mapped[int] = mapped_column(Integer, default=0)
    finished_ts: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")


class BulkItem(Base):
    """One ad inside a bulk operation and where it is in its flow."""

    __tablename__ = "bulk_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    op_id: Mapped[int] = mapped_column(ForeignKey("bulk_operations.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    ad_id: Mapped[int] = mapped_column(BigInteger, index=True)
    new_ad_id: Mapped[int | None] = mapped_column(BigInteger)
    # pending | submitted | in_review | approved | declined | retired | failed | skipped
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    step: Mapped[str] = mapped_column(String(16), default="")  # retire sub-step: pause | withdraw | transfer | archive
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # text, promote_url, tag_id, variant_id
    error: Mapped[str] = mapped_column(Text, default="")
    decline_reason: Mapped[str] = mapped_column(Text, default="")
    withdrawn: Mapped[float] = mapped_column(Float, default=0)
    created_ts: Mapped[int] = mapped_column(Integer, default=0)
    updated_ts: Mapped[int] = mapped_column(Integer, default=0)


class Event(Base):
    """Activity log shown in the panel."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[int] = mapped_column(Integer, index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(24))
    action: Mapped[str] = mapped_column(String(48))
    ad_id: Mapped[int | None] = mapped_column(BigInteger)
    level: Mapped[str] = mapped_column(String(8), default="info")  # info | warn | error
    detail: Mapped[str] = mapped_column(Text, default="")
