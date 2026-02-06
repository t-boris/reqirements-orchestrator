"""Add channel_config table for per-channel settings

Revision ID: 004
Revises: 003
Create Date: 2026-02-05

Stores per-channel configuration like Jira project key.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_config",
        sa.Column("channel_id", sa.String(50), primary_key=True),
        sa.Column("jira_project", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, server_default=sa.func.now(), onupdate=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("channel_config")
