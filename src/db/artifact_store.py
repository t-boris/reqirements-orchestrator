"""Artifact store for review persistence.

Provides CRUD operations for ReviewArtifact and ArtifactLink models.
Reviews are stored as permanent artifacts linked to commits/workitems.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

from src.db.models import (
    ReviewArtifact,
    ArtifactLink,
    ArtifactKind,
    ArtifactLinkType,
    ArtifactTargetType,
)


class ArtifactStore:
    """CRUD operations for review artifacts."""

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def create_tables(self) -> None:
        """Create artifact tables if not exist."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS review_artifacts (
                    artifact_id UUID PRIMARY KEY,
                    channel_id TEXT NOT NULL,
                    source_thread_ts TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    content_hash TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    full_content TEXT NOT NULL,
                    decisions JSONB DEFAULT '[]',
                    risks JSONB DEFAULT '[]',
                    open_questions JSONB DEFAULT '[]',
                    created_at TIMESTAMPTZ NOT NULL,
                    created_by TEXT NOT NULL,
                    approved_by TEXT,
                    approved_at TIMESTAMPTZ
                )
            """)

            await cur.execute("""
                CREATE TABLE IF NOT EXISTS artifact_links (
                    link_id UUID PRIMARY KEY,
                    artifact_id UUID NOT NULL REFERENCES review_artifacts(artifact_id),
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    link_type TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    UNIQUE(artifact_id, target_type, target_id)
                )
            """)

            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_artifacts_channel
                ON review_artifacts(channel_id)
            """)

            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_artifacts_thread
                ON review_artifacts(channel_id, source_thread_ts)
            """)

            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_artifact_links_target
                ON artifact_links(target_type, target_id)
            """)

            await self._conn.commit()

    async def create(
        self,
        channel_id: str,
        thread_ts: str,
        kind: ArtifactKind,
        summary: str,
        full_content: str,
        created_by: str,
        decisions: list[str] | None = None,
        risks: list[str] | None = None,
        open_questions: list[str] | None = None,
    ) -> ReviewArtifact:
        """Create a new review artifact."""
        artifact_id = str(uuid.uuid4())
        content_hash = hashlib.sha256(full_content.encode()).hexdigest()[:16]
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO review_artifacts
                (artifact_id, channel_id, source_thread_ts, kind, version,
                 content_hash, summary, full_content, decisions, risks,
                 open_questions, created_at, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    artifact_id, channel_id, thread_ts, kind.value, 1,
                    content_hash, summary, full_content,
                    json.dumps(decisions or []),
                    json.dumps(risks or []),
                    json.dumps(open_questions or []),
                    now, created_by,
                ),
            )
            await self._conn.commit()

        return ReviewArtifact(
            artifact_id=artifact_id,
            channel_id=channel_id,
            source_thread_ts=thread_ts,
            kind=kind,
            version=1,
            content_hash=content_hash,
            summary=summary,
            full_content=full_content,
            decisions=decisions or [],
            risks=risks or [],
            open_questions=open_questions or [],
            created_at=now,
            created_by=created_by,
        )

    async def get(self, artifact_id: str) -> Optional[ReviewArtifact]:
        """Get artifact by ID."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM review_artifacts WHERE artifact_id = %s",
                (artifact_id,),
            )
            row = await cur.fetchone()

        if not row:
            return None

        return self._row_to_artifact(row)

    async def get_by_thread(
        self,
        channel_id: str,
        thread_ts: str,
    ) -> list[ReviewArtifact]:
        """Get all artifacts for a thread."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT * FROM review_artifacts
                WHERE channel_id = %s AND source_thread_ts = %s
                ORDER BY created_at DESC
                """,
                (channel_id, thread_ts),
            )
            rows = await cur.fetchall()

        return [self._row_to_artifact(row) for row in rows]

    async def get_by_channel(
        self,
        channel_id: str,
        limit: int = 50,
    ) -> list[ReviewArtifact]:
        """Get recent artifacts for a channel."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT * FROM review_artifacts
                WHERE channel_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (channel_id, limit),
            )
            rows = await cur.fetchall()

        return [self._row_to_artifact(row) for row in rows]

    async def approve(
        self,
        artifact_id: str,
        approved_by: str,
    ) -> Optional[ReviewArtifact]:
        """Mark artifact as approved."""
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE review_artifacts
                SET approved_by = %s, approved_at = %s
                WHERE artifact_id = %s
                RETURNING *
                """,
                (approved_by, now, artifact_id),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        if not row:
            return None

        return self._row_to_artifact(row)

    async def add_link(
        self,
        artifact_id: str,
        target_type: ArtifactTargetType,
        target_id: str,
        link_type: ArtifactLinkType,
    ) -> ArtifactLink:
        """Add link from artifact to another entity."""
        link_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO artifact_links
                (link_id, artifact_id, target_type, target_id, link_type, created_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (artifact_id, target_type, target_id) DO NOTHING
                RETURNING *
                """,
                (link_id, artifact_id, target_type.value, target_id, link_type.value, now),
            )
            await self._conn.commit()

        return ArtifactLink(
            link_id=link_id,
            artifact_id=artifact_id,
            target_type=target_type,
            target_id=target_id,
            link_type=link_type,
            created_at=now,
        )

    async def get_links(self, artifact_id: str) -> list[ArtifactLink]:
        """Get all links for an artifact."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM artifact_links WHERE artifact_id = %s",
                (artifact_id,),
            )
            rows = await cur.fetchall()

        return [self._row_to_link(row) for row in rows]

    async def get_artifacts_for_target(
        self,
        target_type: ArtifactTargetType,
        target_id: str,
    ) -> list[ReviewArtifact]:
        """Get all artifacts linked to a target."""
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT a.* FROM review_artifacts a
                JOIN artifact_links l ON a.artifact_id::text = l.artifact_id::text
                WHERE l.target_type = %s AND l.target_id = %s
                ORDER BY a.created_at DESC
                """,
                (target_type.value, target_id),
            )
            rows = await cur.fetchall()

        return [self._row_to_artifact(row) for row in rows]

    def _row_to_artifact(self, row) -> ReviewArtifact:
        """Convert database row to ReviewArtifact."""
        return ReviewArtifact(
            artifact_id=str(row[0]),
            channel_id=row[1],
            source_thread_ts=row[2],
            kind=ArtifactKind(row[3]),
            version=row[4],
            content_hash=row[5],
            summary=row[6],
            full_content=row[7],
            decisions=row[8] if isinstance(row[8], list) else [],
            risks=row[9] if isinstance(row[9], list) else [],
            open_questions=row[10] if isinstance(row[10], list) else [],
            created_at=row[11],
            created_by=row[12],
            approved_by=row[13],
            approved_at=row[14],
        )

    def _row_to_link(self, row) -> ArtifactLink:
        """Convert database row to ArtifactLink."""
        return ArtifactLink(
            link_id=str(row[0]),
            artifact_id=str(row[1]),
            target_type=ArtifactTargetType(row[2]),
            target_id=row[3],
            link_type=ArtifactLinkType(row[4]),
            created_at=row[5],
        )
