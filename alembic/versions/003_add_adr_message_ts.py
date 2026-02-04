"""Add adr_message_ts column to entities_view

Revision ID: 003
Revises: 002
Create Date: 2026-02-04

Stores the ADR (Architecture Decision Record) pinned message timestamp
for decision entities. Used by the projection to track which Slack message
represents the ADR for a decision.

Addresses ISS-008: Amendment projection doesn't update adr_message_ts.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "entities_view",
        sa.Column("adr_message_ts", sa.String(50), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("entities_view", "adr_message_ts")
