"""Entities view projection table

Revision ID: 002
Revises: 001
Create Date: 2026-02-02

Read model tables for projections:
- entities_view: Current entity state for queries
- projection_positions: Track projection progress for idempotency

Based on maro_2_0.md spec Part 4.5 (Projections).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # entities_view - read model for entity queries
    op.create_table(
        "entities_view",
        sa.Column("id", sa.String(36), primary_key=True),  # EntityId (UUID string)
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("lifecycle", sa.String(20), nullable=False),
        sa.Column("channel_id", sa.String(50), nullable=False),
        sa.Column("thread_ts", sa.String(50), nullable=True),
        sa.Column("content", JSONB, nullable=False),
        sa.Column("attribution", JSONB, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("canonical_message_ts", sa.String(50), nullable=True),
        sa.Column("jira_link", JSONB, nullable=True),
        sa.Column("approvals", JSONB, nullable=True),
        sa.Column("objections", JSONB, nullable=True),
        sa.Column("deprecated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by", sa.String(36), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_entities_channel", "entities_view", ["channel_id"])
    op.create_index("ix_entities_lifecycle", "entities_view", ["lifecycle"])
    op.create_index("ix_entities_type", "entities_view", ["entity_type"])

    # projection_positions - track projection progress for idempotency
    op.create_table(
        "projection_positions",
        sa.Column("projection_name", sa.String(100), primary_key=True),
        sa.Column("last_event_id", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("projection_positions")
    op.drop_table("entities_view")
