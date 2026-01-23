"""AuditStore for comprehensive action logging.

Provides persistent audit trail for all external actions including:
- Jira API calls (create, update, transition)
- Draft approvals and rejections
- Conflict resolutions
- WorkItem lifecycle events

Phase 27.5: Part of multi-user support for auditability.
"""
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from psycopg import AsyncConnection


class AuditActionType(str, Enum):
    """Types of auditable actions."""

    # Jira operations
    JIRA_CREATE = "jira_create"
    JIRA_UPDATE = "jira_update"
    JIRA_TRANSITION = "jira_transition"
    JIRA_LINK = "jira_link"
    JIRA_COMMENT = "jira_comment"

    # Draft lifecycle
    DRAFT_APPROVE = "draft_approve"
    DRAFT_REJECT = "draft_reject"
    DRAFT_EDIT = "draft_edit"

    # Conflict resolution
    CONFLICT_RESOLVE = "conflict_resolve"
    CONFLICT_DETECT = "conflict_detect"

    # Decision tracking
    DECISION_APPROVE = "decision_approve"

    # WorkItem lifecycle
    WORKITEM_CREATE = "workitem_create"
    WORKITEM_UPDATE = "workitem_update"
    WORKITEM_STATUS_CHANGE = "workitem_status_change"


class AuditEntry(BaseModel):
    """An audit log entry for an external action.

    Captures the who, what, when, and result of every significant action.
    """

    entry_id: str = Field(description="UUID for this entry")
    channel_id: str = Field(description="Channel where action occurred")
    thread_ts: Optional[str] = Field(default=None, description="Thread if applicable")

    # Action details
    action_type: AuditActionType
    actor_user_id: str = Field(description="User who performed/approved the action")

    # Target
    target_type: str = Field(description="workitem, jira, draft, decision")
    target_id: str = Field(description="ID of target (workitem_id, jira_key, etc.)")

    # Outcome
    outcome: str = Field(description="success, error, skipped")
    error_message: Optional[str] = Field(default=None)
    error_details: Optional[dict] = Field(default=None)

    # Correlation
    request_id: Optional[str] = Field(default=None, description="For request tracing")
    source_message_ts: Optional[str] = Field(default=None, description="Triggering message")
    commit_id: Optional[str] = Field(default=None, description="Related commit entry")

    # Metadata
    created_at: datetime
    metadata: Optional[dict] = Field(default=None, description="Additional context")


class AuditStore:
    """Store for audit log entries.

    Usage:
        async with get_connection() as conn:
            audit = AuditStore(conn)
            await audit.log(
                channel_id=channel,
                action_type=AuditActionType.JIRA_CREATE,
                actor_user_id=user_id,
                target_type="jira",
                target_id=jira_key,
                outcome="success",
            )
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def ensure_table(self) -> None:
        """Create audit_log table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    entry_id UUID PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT,
                    action_type TEXT NOT NULL,
                    actor_user_id TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    error_message TEXT,
                    error_details JSONB,
                    request_id TEXT,
                    source_message_ts TEXT,
                    commit_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    metadata JSONB
                )
            """)

            # Index for channel queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_log_channel
                ON audit_log(channel_id)
            """)

            # Index for actor queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_log_actor
                ON audit_log(actor_user_id)
            """)

            # Index for target queries (type + id)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_log_target
                ON audit_log(target_type, target_id)
            """)

            # Index for time-based queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_log_created
                ON audit_log(created_at DESC)
            """)

            await self._conn.commit()

    async def log(
        self,
        channel_id: str,
        action_type: AuditActionType,
        actor_user_id: str,
        target_type: str,
        target_id: str,
        outcome: str,
        *,
        thread_ts: Optional[str] = None,
        error_message: Optional[str] = None,
        error_details: Optional[dict] = None,
        request_id: Optional[str] = None,
        source_message_ts: Optional[str] = None,
        commit_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> AuditEntry:
        """Log an auditable action.

        Args:
            channel_id: Channel where action occurred.
            action_type: Type of action being logged.
            actor_user_id: User who performed/approved the action.
            target_type: Type of target (workitem, jira, draft, decision).
            target_id: ID of the target (workitem_id, jira_key, etc.).
            outcome: Result of the action (success, error, skipped).
            thread_ts: Thread timestamp if action is thread-specific.
            error_message: Error message if outcome is error.
            error_details: Additional error details as dict.
            request_id: Correlation ID for request tracing.
            source_message_ts: Message that triggered this action.
            commit_id: Related commit entry ID.
            metadata: Additional context as dict.

        Returns:
            AuditEntry: The created audit log entry.
        """
        entry_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO audit_log
                    (entry_id, channel_id, thread_ts, action_type, actor_user_id,
                     target_type, target_id, outcome, error_message, error_details,
                     request_id, source_message_ts, commit_id, created_at, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    entry_id,
                    channel_id,
                    thread_ts,
                    action_type.value,
                    actor_user_id,
                    target_type,
                    target_id,
                    outcome,
                    error_message,
                    json.dumps(error_details) if error_details else None,
                    request_id,
                    source_message_ts,
                    commit_id,
                    now,
                    json.dumps(metadata) if metadata else None,
                ),
            )
            await self._conn.commit()

        return AuditEntry(
            entry_id=entry_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            action_type=action_type,
            actor_user_id=actor_user_id,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            error_message=error_message,
            error_details=error_details,
            request_id=request_id,
            source_message_ts=source_message_ts,
            commit_id=commit_id,
            created_at=now,
            metadata=metadata,
        )

    async def get_for_channel(
        self,
        channel_id: str,
        limit: int = 50,
        action_types: Optional[list[AuditActionType]] = None,
    ) -> list[AuditEntry]:
        """Get recent audit entries for a channel.

        Args:
            channel_id: Slack channel ID.
            limit: Maximum entries to return (default 50).
            action_types: Optional filter by action types.

        Returns:
            List of AuditEntry objects, ordered by created_at DESC.
        """
        query = """
            SELECT entry_id, channel_id, thread_ts, action_type, actor_user_id,
                   target_type, target_id, outcome, error_message, error_details,
                   request_id, source_message_ts, commit_id, created_at, metadata
            FROM audit_log
            WHERE channel_id = %s
        """
        params: list = [channel_id]

        if action_types:
            type_values = [t.value for t in action_types]
            placeholders = ", ".join(["%s"] * len(type_values))
            query += f" AND action_type IN ({placeholders})"
            params.extend(type_values)

        query += " ORDER BY created_at DESC LIMIT %s"
        params.append(limit)

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()

        return [self._row_to_entry(row) for row in rows]

    async def get_for_target(
        self,
        target_type: str,
        target_id: str,
    ) -> list[AuditEntry]:
        """Get audit entries for a specific target (workitem, jira issue).

        Args:
            target_type: Type of target (workitem, jira, draft, decision).
            target_id: ID of the target.

        Returns:
            List of AuditEntry objects for this target, ordered by created_at DESC.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT entry_id, channel_id, thread_ts, action_type, actor_user_id,
                       target_type, target_id, outcome, error_message, error_details,
                       request_id, source_message_ts, commit_id, created_at, metadata
                FROM audit_log
                WHERE target_type = %s AND target_id = %s
                ORDER BY created_at DESC
                """,
                (target_type, target_id),
            )
            rows = await cur.fetchall()

        return [self._row_to_entry(row) for row in rows]

    async def get_for_user(
        self,
        actor_user_id: str,
        limit: int = 50,
    ) -> list[AuditEntry]:
        """Get audit entries by actor.

        Args:
            actor_user_id: User ID of the actor.
            limit: Maximum entries to return (default 50).

        Returns:
            List of AuditEntry objects for this actor, ordered by created_at DESC.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT entry_id, channel_id, thread_ts, action_type, actor_user_id,
                       target_type, target_id, outcome, error_message, error_details,
                       request_id, source_message_ts, commit_id, created_at, metadata
                FROM audit_log
                WHERE actor_user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (actor_user_id, limit),
            )
            rows = await cur.fetchall()

        return [self._row_to_entry(row) for row in rows]

    async def get_for_thread(
        self,
        channel_id: str,
        thread_ts: str,
        limit: int = 50,
    ) -> list[AuditEntry]:
        """Get audit entries for a specific thread.

        Args:
            channel_id: Slack channel ID.
            thread_ts: Thread timestamp.
            limit: Maximum entries to return (default 50).

        Returns:
            List of AuditEntry objects for this thread, ordered by created_at DESC.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT entry_id, channel_id, thread_ts, action_type, actor_user_id,
                       target_type, target_id, outcome, error_message, error_details,
                       request_id, source_message_ts, commit_id, created_at, metadata
                FROM audit_log
                WHERE channel_id = %s AND thread_ts = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (channel_id, thread_ts, limit),
            )
            rows = await cur.fetchall()

        return [self._row_to_entry(row) for row in rows]

    def _row_to_entry(self, row: tuple) -> AuditEntry:
        """Convert database row to AuditEntry model.

        Args:
            row: Tuple from database query.

        Returns:
            AuditEntry model instance.
        """
        return AuditEntry(
            entry_id=str(row[0]),
            channel_id=row[1],
            thread_ts=row[2],
            action_type=AuditActionType(row[3]),
            actor_user_id=row[4],
            target_type=row[5],
            target_id=row[6],
            outcome=row[7],
            error_message=row[8],
            error_details=row[9] if row[9] else None,
            request_id=row[10],
            source_message_ts=row[11],
            commit_id=row[12],
            created_at=row[13],
            metadata=row[14] if row[14] else None,
        )
