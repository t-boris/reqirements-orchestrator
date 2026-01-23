"""Approval records storage for idempotent draft approvals.

Stores approval records in PostgreSQL with unique constraint on (session_id, draft_hash)
to ensure first-wins semantics for button clicks.
"""
import logging
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


class ApprovalRecord(BaseModel):
    """Record of a draft approval.

    Enhanced in Phase 27.4 with state binding:
    - state_version: Version from AgentState.state_version at approval time
    - ui_version: Version from AgentState.ui_version at approval time

    State binding ensures approvals are tied to exact state version,
    preventing approval of outdated content.
    """

    id: Optional[str] = Field(default=None, description="UUID of approval record")
    session_id: str = Field(description="Session ID for the approval")
    draft_hash: str = Field(description="Hash of draft content at time of approval")
    approved_by: str = Field(description="Slack user ID who approved")
    approved_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = Field(default="approved", description="Status: approved, rejected")

    # State binding (Phase 27.4)
    state_version: int = Field(default=0, description="State version at approval time")
    ui_version: int = Field(default=0, description="UI version at approval time")


class ApprovalStore:
    """PostgreSQL store for approval records.

    Provides idempotent approval recording with unique constraint
    on (session_id, draft_hash).
    """

    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def create_tables(self) -> None:
        """Create approval_records table if not exists.

        Phase 27.4: Added state_version and ui_version columns for state binding.
        """
        sql = """
        CREATE TABLE IF NOT EXISTS approval_records (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id TEXT NOT NULL,
            draft_hash TEXT NOT NULL,
            approved_by TEXT NOT NULL,
            approved_at TIMESTAMPTZ DEFAULT NOW(),
            status TEXT DEFAULT 'approved',
            state_version INTEGER DEFAULT 0,
            ui_version INTEGER DEFAULT 0,
            UNIQUE(session_id, draft_hash)
        );

        CREATE INDEX IF NOT EXISTS idx_approval_records_session
            ON approval_records(session_id);
        """
        async with self.conn.cursor() as cur:
            await cur.execute(sql)
            # Add columns if they don't exist (migration for existing tables)
            await cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'approval_records' AND column_name = 'state_version'
                    ) THEN
                        ALTER TABLE approval_records ADD COLUMN state_version INTEGER DEFAULT 0;
                    END IF;
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'approval_records' AND column_name = 'ui_version'
                    ) THEN
                        ALTER TABLE approval_records ADD COLUMN ui_version INTEGER DEFAULT 0;
                    END IF;
                END $$;
            """)
        await self.conn.commit()
        logger.debug("Created/migrated approval_records table")

    async def record_approval(
        self,
        session_id: str,
        draft_hash: str,
        approved_by: str,
        status: str = "approved",
        state_version: int = 0,
        ui_version: int = 0,
    ) -> bool:
        """Record an approval. Returns True if new, False if duplicate.

        Uses INSERT with ON CONFLICT DO NOTHING to handle race conditions.
        First approval wins - subsequent attempts are ignored.

        Phase 27.4: Added state_version and ui_version for state binding.

        Args:
            session_id: Session ID for the draft
            draft_hash: Hash of draft content
            approved_by: Slack user ID approving
            status: Status (approved or rejected)
            state_version: State version at approval time (Phase 27.4)
            ui_version: UI version at approval time (Phase 27.4)

        Returns:
            True if this is a new approval record (first wins)
            False if approval already exists (duplicate)
        """
        sql = """
        INSERT INTO approval_records (session_id, draft_hash, approved_by, status, state_version, ui_version)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (session_id, draft_hash) DO NOTHING
        RETURNING id;
        """
        async with self.conn.cursor() as cur:
            await cur.execute(sql, (session_id, draft_hash, approved_by, status, state_version, ui_version))
            result = await cur.fetchone()
        await self.conn.commit()

        is_new = result is not None
        logger.info(
            f"Approval record: {'new' if is_new else 'duplicate'}",
            extra={
                "session_id": session_id,
                "draft_hash": draft_hash,
                "approved_by": approved_by,
                "state_version": state_version,
                "ui_version": ui_version,
            },
        )
        return is_new

    async def get_approval(
        self,
        session_id: str,
        draft_hash: str,
    ) -> Optional[ApprovalRecord]:
        """Get approval record if exists.

        Args:
            session_id: Session ID for the draft
            draft_hash: Hash of draft content

        Returns:
            ApprovalRecord if exists, None otherwise
        """
        sql = """
        SELECT id, session_id, draft_hash, approved_by, approved_at, status, state_version, ui_version
        FROM approval_records
        WHERE session_id = %s AND draft_hash = %s;
        """
        async with self.conn.cursor() as cur:
            await cur.execute(sql, (session_id, draft_hash))
            row = await cur.fetchone()

        if not row:
            return None

        return ApprovalRecord(
            id=str(row[0]),
            session_id=row[1],
            draft_hash=row[2],
            approved_by=row[3],
            approved_at=row[4],
            status=row[5],
            state_version=row[6] or 0,
            ui_version=row[7] or 0,
        )

    async def get_approver(
        self,
        session_id: str,
        draft_hash: str,
    ) -> Optional[str]:
        """Get user ID who approved the draft.

        Convenience method for feedback messages.

        Args:
            session_id: Session ID for the draft
            draft_hash: Hash of draft content

        Returns:
            User ID string if approved, None otherwise
        """
        sql = """
        SELECT approved_by
        FROM approval_records
        WHERE session_id = %s AND draft_hash = %s;
        """
        async with self.conn.cursor() as cur:
            await cur.execute(sql, (session_id, draft_hash))
            row = await cur.fetchone()

        return row[0] if row else None

    async def get_session_approvals(
        self,
        session_id: str,
    ) -> list[ApprovalRecord]:
        """Get all approval records for a session.

        Useful for audit trail.

        Args:
            session_id: Session ID to query

        Returns:
            List of ApprovalRecords for the session
        """
        sql = """
        SELECT id, session_id, draft_hash, approved_by, approved_at, status, state_version, ui_version
        FROM approval_records
        WHERE session_id = %s
        ORDER BY approved_at DESC;
        """
        async with self.conn.cursor() as cur:
            await cur.execute(sql, (session_id,))
            rows = await cur.fetchall()

        return [
            ApprovalRecord(
                id=str(row[0]),
                session_id=row[1],
                draft_hash=row[2],
                approved_by=row[3],
                approved_at=row[4],
                status=row[5],
                state_version=row[6] or 0,
                ui_version=row[7] or 0,
            )
            for row in rows
        ]
