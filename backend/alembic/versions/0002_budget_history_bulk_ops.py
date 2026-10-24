"""budget history, archived ads, bulk operations

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-24 09:30:00
"""

import time
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ads", schema=None) as batch_op:
        batch_op.add_column(sa.Column("funded_since_ts", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("empty_since_ts", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("archived_ts", sa.Integer(), nullable=False, server_default="0"))
    # The panel has no budget history for ads that already exist: count their funded time "from now",
    # so no ad is judged stalled on spending that happened while it may have had no budget.
    op.execute(
        sa.text("UPDATE ads SET funded_since_ts = :now WHERE remaining_budget > 0.01").bindparams(now=int(time.time()))
    )

    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("bulk_item_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("params", sa.JSON(), nullable=False, server_default="{}"))
        batch_op.create_index(batch_op.f("ix_jobs_bulk_item_id"), ["bulk_item_id"], unique=False)

    op.create_table(
        "ad_budget_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("ad_id", sa.BigInteger(), nullable=False),
        sa.Column("ts", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("remaining", sa.Float(), nullable=False),
        sa.Column("actor", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_ad_budget_events_account_id_accounts"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ad_budget_events")),
    )
    with op.batch_alter_table("ad_budget_events", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ad_budget_events_account_id"), ["account_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_ad_budget_events_ad_id"), ["ad_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_ad_budget_events_ts"), ["ts"], unique=False)

    op.create_table(
        "bulk_operations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("created_ts", sa.Integer(), nullable=False),
        sa.Column("updated_ts", sa.Integer(), nullable=False),
        sa.Column("last_batch_ts", sa.Integer(), nullable=False),
        sa.Column("finished_ts", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_bulk_operations_account_id_accounts"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bulk_operations")),
    )
    with op.batch_alter_table("bulk_operations", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_bulk_operations_account_id"), ["account_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_bulk_operations_status"), ["status"], unique=False)

    op.create_table(
        "bulk_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("op_id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("ad_id", sa.BigInteger(), nullable=False),
        sa.Column("new_ad_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("step", sa.String(length=16), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("decline_reason", sa.Text(), nullable=False),
        sa.Column("withdrawn", sa.Float(), nullable=False),
        sa.Column("created_ts", sa.Integer(), nullable=False),
        sa.Column("updated_ts", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name=op.f("fk_bulk_items_account_id_accounts"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["op_id"], ["bulk_operations.id"], name=op.f("fk_bulk_items_op_id_bulk_operations"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bulk_items")),
    )
    with op.batch_alter_table("bulk_items", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_bulk_items_account_id"), ["account_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_bulk_items_ad_id"), ["ad_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_bulk_items_op_id"), ["op_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_bulk_items_status"), ["status"], unique=False)


def downgrade() -> None:
    op.drop_table("bulk_items")
    op.drop_table("bulk_operations")
    op.drop_table("ad_budget_events")
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_jobs_bulk_item_id"))
        batch_op.drop_column("params")
        batch_op.drop_column("bulk_item_id")
    with op.batch_alter_table("ads", schema=None) as batch_op:
        batch_op.drop_column("archived_ts")
        batch_op.drop_column("archived")
        batch_op.drop_column("empty_since_ts")
        batch_op.drop_column("funded_since_ts")
