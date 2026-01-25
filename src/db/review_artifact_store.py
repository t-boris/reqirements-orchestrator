"""ReviewArtifactStore with async CRUD operations using psycopg v3.

Provides database persistence for ReviewArtifact entities.
Checkpoint becomes cache, DB is source of truth.
"""
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from psycopg import AsyncConnection

from src.schemas.review_artifact import ReviewArtifact


class ReviewArtifactStore:
    """Store for ReviewArtifact entities with CRUD operations.

    Usage:
        async with get_connection() as conn:
            store = ReviewArtifactStore(conn)
            artifact = await store.create(ReviewArtifact(...))
    """

    def __init__(self, conn: AsyncConnection) -> None:
        """Initialize store with an async connection.

        Args:
            conn: Async psycopg connection from the pool.
        """
        self._conn = conn

    async def create_tables(self) -> None:
        """Create review_artifacts table if not exists.

        Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS review_artifacts (
                    id UUID PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    thread_ts TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    updated_summary TEXT,
                    kind TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    persona TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """)

            # Index on (channel_id, thread_ts) for thread lookups
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_review_artifacts_channel_thread
                ON review_artifacts(channel_id, thread_ts)
            """)

            # Index on channel_id for channel-level queries
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_review_artifacts_channel
                ON review_artifacts(channel_id)
            """)

            await self._conn.commit()

    async def create(self, artifact: ReviewArtifact) -> ReviewArtifact:
        """Create a new review artifact.

        Args:
            artifact: ReviewArtifact to persist.

        Returns:
            ReviewArtifact: The persisted artifact with database defaults applied.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO review_artifacts (
                    id, channel_id, thread_ts, topic, summary, updated_summary,
                    kind, version, persona, content_hash, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, channel_id, thread_ts, topic, summary, updated_summary,
                          kind, version, persona, content_hash, created_at, updated_at
                """,
                (
                    str(artifact.id),
                    artifact.channel_id,
                    artifact.thread_ts,
                    artifact.topic,
                    artifact.summary,
                    artifact.updated_summary,
                    artifact.kind,
                    artifact.version,
                    artifact.persona,
                    artifact.content_hash,
                    artifact.created_at,
                    artifact.updated_at,
                ),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        return self._row_to_artifact(row)

    async def get(self, artifact_id: UUID) -> Optional[ReviewArtifact]:
        """Get review artifact by ID.

        Args:
            artifact_id: UUID of the artifact.

        Returns:
            ReviewArtifact if found, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, thread_ts, topic, summary, updated_summary,
                       kind, version, persona, content_hash, created_at, updated_at
                FROM review_artifacts
                WHERE id = %s
                """,
                (str(artifact_id),),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_artifact(row)

    async def get_for_thread(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> Optional[ReviewArtifact]:
        """Get the latest review artifact for a thread.

        Args:
            channel_id: Slack channel ID.
            thread_ts: Thread timestamp.

        Returns:
            ReviewArtifact if found, None otherwise.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, thread_ts, topic, summary, updated_summary,
                       kind, version, persona, content_hash, created_at, updated_at
                FROM review_artifacts
                WHERE channel_id = %s AND thread_ts = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (channel_id, thread_ts),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_artifact(row)

    async def update(
        self,
        artifact_id: UUID,
        **updates,
    ) -> Optional[ReviewArtifact]:
        """Update review artifact with version increment.

        Args:
            artifact_id: UUID of the artifact to update.
            **updates: Fields to update (summary, updated_summary, topic, etc.).

        Returns:
            Updated ReviewArtifact if found, None otherwise.
        """
        # Build dynamic update query
        allowed_fields = {"summary", "updated_summary", "topic", "content_hash", "kind"}
        set_clauses = []
        params = []

        for field, value in updates.items():
            if field in allowed_fields:
                set_clauses.append(f"{field} = %s")
                params.append(value)

        if not set_clauses:
            # No valid updates, just return current
            return await self.get(artifact_id)

        # Always increment version and update timestamp
        set_clauses.append("version = version + 1")
        set_clauses.append("updated_at = %s")
        params.append(datetime.now(timezone.utc))
        params.append(str(artifact_id))

        query = f"""
            UPDATE review_artifacts
            SET {', '.join(set_clauses)}
            WHERE id = %s
            RETURNING id, channel_id, thread_ts, topic, summary, updated_summary,
                      kind, version, persona, content_hash, created_at, updated_at
        """

        async with self._conn.cursor() as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            return None

        return self._row_to_artifact(row)

    async def list_for_channel(
        self,
        channel_id: str,
        limit: int = 10,
    ) -> list[ReviewArtifact]:
        """List recent review artifacts for a channel.

        Args:
            channel_id: Slack channel ID.
            limit: Maximum artifacts to return (default 10).

        Returns:
            List of ReviewArtifact objects, ordered by updated_at DESC.
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT id, channel_id, thread_ts, topic, summary, updated_summary,
                       kind, version, persona, content_hash, created_at, updated_at
                FROM review_artifacts
                WHERE channel_id = %s
                ORDER BY updated_at DESC
                LIMIT %s
                """,
                (channel_id, limit),
            )
            rows = await cur.fetchall()

        return [self._row_to_artifact(row) for row in rows]

    def _row_to_artifact(self, row: tuple) -> ReviewArtifact:
        """Convert database row to ReviewArtifact model.

        Args:
            row: Tuple from database query.
                Expected order (12 columns):
                0: id, 1: channel_id, 2: thread_ts, 3: topic,
                4: summary, 5: updated_summary, 6: kind, 7: version,
                8: persona, 9: content_hash, 10: created_at, 11: updated_at

        Returns:
            ReviewArtifact model instance.
        """
        return ReviewArtifact(
            id=UUID(str(row[0])),
            channel_id=row[1],
            thread_ts=row[2],
            topic=row[3],
            summary=row[4],
            updated_summary=row[5],
            kind=row[6],
            version=row[7],
            persona=row[8],
            content_hash=row[9],
            created_at=row[10],
            updated_at=row[11],
        )
