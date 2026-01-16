"""Event store for idempotency tracking.

Tracks processed event IDs to prevent duplicate processing.
HA-ready: uses PostgreSQL with 24h TTL.
"""
import logging
from datetime import datetime, timedelta, timezone

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)

# TTL for processed events (24 hours)
EVENT_TTL_HOURS = 24


class EventStore:
    """Store for tracking processed events.

    Key format: (team_id, event_id)
    For button clicks without stable event_id: (team_id, action_id:message_ts:user_id)
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection.
        """
        self._conn = conn

    async def ensure_table(self) -> None:
        """Create events table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS processed_events (
                    team_id TEXT NOT NULL,
                    event_id TEXT NOT NULL,
                    processed_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (team_id, event_id)
                )
            """)
            # Index for cleanup query
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_processed_events_time
                ON processed_events (processed_at)
            """)
            await self._conn.commit()

    async def is_processed(self, team_id: str, event_id: str) -> bool:
        """Check if event was already processed.

        Args:
            team_id: Slack team/workspace ID
            event_id: Event ID (or fallback key for buttons)

        Returns:
            True if event was already processed
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT 1 FROM processed_events
                WHERE team_id = %s AND event_id = %s
                """,
                (team_id, event_id),
            )
            result = await cur.fetchone()
        return result is not None

    async def mark_processed(self, team_id: str, event_id: str) -> bool:
        """Mark event as processed.

        Uses INSERT ... ON CONFLICT DO NOTHING for race safety.

        Args:
            team_id: Slack team/workspace ID
            event_id: Event ID (or fallback key for buttons)

        Returns:
            True if this was first processing (inserted), False if already existed
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO processed_events (team_id, event_id)
                VALUES (%s, %s)
                ON CONFLICT (team_id, event_id) DO NOTHING
                """,
                (team_id, event_id),
            )
            # Check rowcount to determine if insert happened
            inserted = cur.rowcount == 1
            await self._conn.commit()
        return inserted

    async def cleanup_old_events(self, hours: int = EVENT_TTL_HOURS) -> int:
        """Remove events older than TTL.

        Should be called periodically (e.g., hourly cron).

        Args:
            hours: TTL in hours (default 24)

        Returns:
            Number of events deleted
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM processed_events
                WHERE processed_at < %s
                """,
                (cutoff,),
            )
            count = cur.rowcount
            await self._conn.commit()
        if count > 0:
            logger.info(f"Cleaned up {count} old events (older than {hours}h)")
        return count


def make_button_event_id(action_id: str, message_ts: str, user_id: str) -> str:
    """Create fallback event ID for button clicks.

    Use when Slack doesn't provide stable event_id.
    Format: action_id:message_ts:user_id
    """
    return f"{action_id}:{message_ts}:{user_id}"
