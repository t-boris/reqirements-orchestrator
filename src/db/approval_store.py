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
    """Record of a draft approval."""

    id: Optional[str] = Field(default=None, description="UUID of approval record")
    session_id: str = Field(description="Session ID for the approval")
    draft_hash: str = Field(description="Hash of draft content at time of approval")
    approved_by: str = Field(description="Slack user ID who approved")
    approved_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = Field(default="approved", description="Status: approved, rejected")


class ApprovalStore:
    """PostgreSQL store for approval records.

    Provides idempotent approval recording with unique constraint
    on (session_id, draft_hash).
    """

    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def create_tables(self) -> None:
        """Create approval_records table if not exists."""
        sql = """
        CREATE TABLE IF NOT EXISTS approval_records (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id TEXT NOT NULL,
            draft_hash TEXT NOT NULL,
            approved_by TEXT NOT NULL,
            approved_at TIMESTAMPTZ DEFAULT NOW(),
            status TEXT DEFAULT 'approved',
            UNIQUE(session_id, draft_hash)
        );

        CREATE INDEX IF NOT EXISTS idx_approval_records_session
            ON approval_records(session_id);
        """
        async with self.conn.cursor() as cur:
            await cur.execute(sql)
        await self.conn.commit()
        logger.debug("Created approval_records table")

    async def record_approval(
        self,
        session_id: str,
        draft_hash: str,
        approved_by: str,
        status: str = "approved",
    ) -> bool:
        """Record an approval. Returns True if new, False if duplicate.

        Uses INSERT with ON CONFLICT DO NOTHING to handle race conditions.
        First approval wins - subsequent attempts are ignored.

        Args:
            session_id: Session ID for the draft
            draft_hash: Hash of draft content
            approved_by: Slack user ID approving
            status: Status (approved or rejected)

        Returns:
            True if this is a new approval record (first wins)
            False if approval already exists (duplicate)
        """
        sql = """
        INSERT INTO approval_records (session_id, draft_hash, approved_by, status)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (session_id, draft_hash) DO NOTHING
        RETURNING id;
        """
        async with self.conn.cursor() as cur:
            await cur.execute(sql, (session_id, draft_hash, approved_by, status))
            result = await cur.fetchone()
        await self.conn.commit()

        is_new = result is not None
        logger.info(
            f"Approval record: {'new' if is_new else 'duplicate'}",
            extra={
                "session_id": session_id,
                "draft_hash": draft_hash,
                "approved_by": approved_by,
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
        SELECT id, session_id, draft_hash, approved_by, approved_at, status
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
        SELECT id, session_id, draft_hash, approved_by, approved_at, status
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
            )
            for row in rows
        ]
