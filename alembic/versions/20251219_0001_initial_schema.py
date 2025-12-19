"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2025-12-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Events table
    op.create_table(
        "events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("channel_id", sa.String(50), nullable=False, index=True),
        sa.Column("user_id", sa.String(50), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False, default=dict),
        sa.Column("timestamp", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_events_channel_sequence",
        "events",
        ["channel_id", "sequence"],
    )

    # Graph snapshots table
    op.create_table(
        "graph_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.String(50), nullable=False, index=True),
        sa.Column("sequence", sa.Integer, nullable=False),
        sa.Column("graph_data", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_snapshots_channel_sequence",
        "graph_snapshots",
        ["channel_id", "sequence"],
    )

    # Channel configs table
    op.create_table(
        "channel_configs",
        sa.Column("channel_id", sa.String(50), primary_key=True),
        sa.Column("jira_project_key", sa.String(20), nullable=True),
        sa.Column("jira_project_id", sa.String(20), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, default=True),
        sa.Column("custom_settings", sa.JSON, nullable=False, default=dict),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    # Audit logs table
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.String(50), nullable=False, index=True),
        sa.Column("user_id", sa.String(50), nullable=False, index=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.String(50), nullable=True),
        sa.Column("details", sa.JSON, nullable=False, default=dict),
        sa.Column("timestamp", sa.DateTime, nullable=False, index=True),
    )
    op.create_index(
        "ix_audit_channel_timestamp",
        "audit_logs",
        ["channel_id", "timestamp"],
    )

    # Sync history table
    op.create_table(
        "sync_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("channel_id", sa.String(50), nullable=False, index=True),
        sa.Column("user_id", sa.String(50), nullable=False),
        sa.Column("target_system", sa.String(50), nullable=False),
        sa.Column("project_key", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("synced_count", sa.Integer, nullable=False, default=0),
        sa.Column("failed_count", sa.Integer, nullable=False, default=0),
        sa.Column("details", sa.JSON, nullable=False, default=dict),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("completed_at", sa.DateTime, nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sync_history")
    op.drop_table("audit_logs")
    op.drop_table("channel_configs")
    op.drop_table("graph_snapshots")
    op.drop_table("events")
