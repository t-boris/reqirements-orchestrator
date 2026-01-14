"""Jira operations storage for idempotency and audit trail.

Stores Jira operation records in PostgreSQL with unique constraint on
(session_id, draft_hash, operation) to ensure first-wins semantics
and prevent duplicate Jira ticket creation from Slack retries.
"""
import logging
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field
from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


class JiraOperationRecord(BaseModel):
    """Record of a Jira operation."""

    id: Optional[str] = Field(default=None, description="UUID of operation record")
    session_id: str = Field(description="Session ID for the operation")
    draft_hash: str = Field(description="Hash of draft content")
    operation: str = Field(description="Operation type: jira_create, jira_update")
    jira_key: Optional[str] = Field(default=None, description="Resulting Jira key (PROJ-123)")
    created_by: str = Field(description="User who triggered the operation")
    approved_by: str = Field(description="User who approved (from approval record)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = Field(default="pending", description="Status: pending, success, failed")
    error_message: Optional[str] = Field(default=None, description="Error message if failed")


class JiraOperationStore:
    """PostgreSQL store for Jira operation records.

    Provides idempotent operation recording with unique constraint
    on (session_id, draft_hash, operation).

    The idempotency key is: (session_id, draft_hash, "jira_create")
    - Same session + same draft hash = same operation
    - Unique constraint prevents duplicate creates from Slack retries
    """

    def __init__(self, conn: AsyncConnection):
        self.conn = conn

    async def create_tables(self) -> None:
        """Create jira_operations table if not exists."""
        sql = """
        CREATE TABLE IF NOT EXISTS jira_operations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id TEXT NOT NULL,
            draft_hash TEXT NOT NULL,
            operation TEXT NOT NULL,
            jira_key TEXT,
            created_by TEXT NOT NULL,
            approved_by TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            UNIQUE(session_id, draft_hash, operation)
        );

        CREATE INDEX IF NOT EXISTS idx_jira_operations_session
            ON jira_operations(session_id);

        CREATE INDEX IF NOT EXISTS idx_jira_operations_jira_key
            ON jira_operations(jira_key);
        """
        async with self.conn.cursor() as cur:
            await cur.execute(sql)
        await self.conn.commit()
        logger.debug("Created jira_operations table")

    async def record_operation_start(
        self,
        session_id: str,
        draft_hash: str,
        operation: str,
        created_by: str,
        approved_by: str,
    ) -> bool:
        """Record the start of an operation. Returns True if new (first wins).

        Uses INSERT with ON CONFLICT DO NOTHING to handle race conditions.
        First operation wins - subsequent attempts are ignored.

        Args:
            session_id: Session ID for the operation
            draft_hash: Hash of draft content
            operation: Operation type (e.g., "jira_create")
            created_by: User who triggered the operation
            approved_by: User who approved (from approval record)

        Returns:
            True if this is a new operation record (first wins)
            False if operation already exists (duplicate)
        """
        sql = """
        INSERT INTO jira_operations (session_id, draft_hash, operation, created_by, approved_by, status)
        VALUES (%s, %s, %s, %s, %s, 'pending')
        ON CONFLICT (session_id, draft_hash, operation) DO NOTHING
        RETURNING id;
        """
        async with self.conn.cursor() as cur:
            await cur.execute(sql, (session_id, draft_hash, operation, created_by, approved_by))
            result = await cur.fetchone()
        await self.conn.commit()

        is_new = result is not None
        logger.info(
            f"Operation record: {'new' if is_new else 'duplicate'}",
            extra={
                "session_id": session_id,
                "draft_hash": draft_hash,
                "operation": operation,
                "is_new": is_new,
            },
        )
        return is_new

    async def mark_success(
        self,
        session_id: str,
        draft_hash: str,
        operation: str,
        jira_key: str,
    ) -> None:
        """Mark operation as successful and store the Jira key.

        Args:
            session_id: Session ID for the operation
            draft_hash: Hash of draft content
            operation: Operation type (e.g., "jira_create")
            jira_key: Created Jira issue key (e.g., PROJ-123)
        """
        sql = """
        UPDATE jira_operations
        SET status = 'success', jira_key = %s
        WHERE session_id = %s AND draft_hash = %s AND operation = %s;
        """
        async with self.conn.cursor() as cur:
            await cur.execute(sql, (jira_key, session_id, draft_hash, operation))
        await self.conn.commit()

        logger.info(
            "Operation marked success",
            extra={
                "session_id": session_id,
                "draft_hash": draft_hash,
                "operation": operation,
                "jira_key": jira_key,
            },
        )

    async def mark_failed(
        self,
        session_id: str,
        draft_hash: str,
        operation: str,
        error_message: str,
    ) -> None:
        """Mark operation as failed and store the error.

        Args:
            session_id: Session ID for the operation
            draft_hash: Hash of draft content
            operation: Operation type (e.g., "jira_create")
            error_message: Error message describing the failure
        """
        sql = """
        UPDATE jira_operations
        SET status = 'failed', error_message = %s
        WHERE session_id = %s AND draft_hash = %s AND operation = %s;
        """
        async with self.conn.cursor() as cur:
            await cur.execute(sql, (error_message, session_id, draft_hash, operation))
        await self.conn.commit()

        logger.warning(
            "Operation marked failed",
            extra={
                "session_id": session_id,
                "draft_hash": draft_hash,
                "operation": operation,
                "error_message": error_message,
            },
        )

    async def get_operation(
        self,
        session_id: str,
        draft_hash: str,
        operation: str,
    ) -> Optional[JiraOperationRecord]:
        """Get operation record if exists.

        Args:
            session_id: Session ID for the operation
            draft_hash: Hash of draft content
            operation: Operation type (e.g., "jira_create")

        Returns:
            JiraOperationRecord if exists, None otherwise
        """
        sql = """
        SELECT id, session_id, draft_hash, operation, jira_key,
               created_by, approved_by, created_at, status, error_message
        FROM jira_operations
        WHERE session_id = %s AND draft_hash = %s AND operation = %s;
        """
        async with self.conn.cursor() as cur:
            await cur.execute(sql, (session_id, draft_hash, operation))
            row = await cur.fetchone()

        if not row:
            return None

        return JiraOperationRecord(
            id=str(row[0]),
            session_id=row[1],
            draft_hash=row[2],
            operation=row[3],
            jira_key=row[4],
            created_by=row[5],
            approved_by=row[6],
            created_at=row[7],
            status=row[8],
            error_message=row[9],
        )

    async def was_already_created(
        self,
        session_id: str,
        draft_hash: str,
    ) -> bool:
        """Check if a jira_create operation already succeeded.

        This is the primary idempotency check. Returns True if:
        - An operation exists for this session_id + draft_hash
        - The operation status is 'success'

        Args:
            session_id: Session ID for the operation
            draft_hash: Hash of draft content

        Returns:
            True if already created successfully, False otherwise
        """
        sql = """
        SELECT 1
        FROM jira_operations
        WHERE session_id = %s
          AND draft_hash = %s
          AND operation = 'jira_create'
          AND status = 'success';
        """
        async with self.conn.cursor() as cur:
            await cur.execute(sql, (session_id, draft_hash))
            row = await cur.fetchone()

        return row is not None

    async def get_session_operations(
        self,
        session_id: str,
    ) -> list[JiraOperationRecord]:
        """Get all operation records for a session.

        Useful for audit trail.

        Args:
            session_id: Session ID to query

        Returns:
            List of JiraOperationRecords for the session
        """
        sql = """
        SELECT id, session_id, draft_hash, operation, jira_key,
               created_by, approved_by, created_at, status, error_message
        FROM jira_operations
        WHERE session_id = %s
        ORDER BY created_at DESC;
        """
        async with self.conn.cursor() as cur:
            await cur.execute(sql, (session_id,))
            rows = await cur.fetchall()

        return [
            JiraOperationRecord(
                id=str(row[0]),
                session_id=row[1],
                draft_hash=row[2],
                operation=row[3],
                jira_key=row[4],
                created_by=row[5],
                approved_by=row[6],
                created_at=row[7],
                status=row[8],
                error_message=row[9],
            )
            for row in rows
        ]
