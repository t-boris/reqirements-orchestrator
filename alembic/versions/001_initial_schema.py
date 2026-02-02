"""Initial event store schema

Revision ID: 001
Revises:
Create Date: 2026-02-02

Event store tables for event sourcing:
- channel_events: Main event store with optimistic concurrency
- channel_snapshots: Snapshot storage for fast aggregate loading
- outbox_events: Outbox pattern for reliable projection updates

Based on:
- maro_2_0.md spec Part 4.4
- 01-CONTEXT.md requirements
- 01-RESEARCH.md patterns
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # channel_events - main event store
    op.create_table(
        "channel_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("aggregate_id", sa.String(50), nullable=False),  # ChannelId
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("actor_id", sa.String(50), nullable=False),
        sa.Column("correlation_id", UUID(as_uuid=True), nullable=True),
        sa.Column("causation_id", UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        # Unique constraint for optimistic concurrency
        sa.UniqueConstraint("aggregate_id", "version", name="uq_aggregate_version"),
    )
    op.create_index(
        "ix_channel_events_aggregate_id", "channel_events", ["aggregate_id"]
    )
    op.create_index("ix_channel_events_event_type", "channel_events", ["event_type"])

    # channel_snapshots - for fast aggregate loading
    op.create_table(
        "channel_snapshots",
        sa.Column("aggregate_id", sa.String(50), primary_key=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("state", JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )

    # outbox_events - for reliable projection updates
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("aggregate_id", sa.String(50), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", JSONB, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("retries", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_outbox_unprocessed",
        "outbox_events",
        ["status"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("channel_snapshots")
    op.drop_table("channel_events")
