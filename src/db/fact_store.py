"""Fact store for context persistence.

Stores structured facts with eviction policy:
- Max facts per scope: thread=50, epic=200, channel=300
- Eviction by LRU or lowest confidence
- Merge by canonical_id (update instead of append)
"""
import hashlib
import logging
from typing import Optional

from psycopg import AsyncConnection

from src.schemas.state import Fact, FACT_LIMITS

logger = logging.getLogger(__name__)


def compute_canonical_id(text: str, scope: str, fact_type: str) -> str:
    """Compute canonical ID for fact deduplication.

    Hash of normalized text + scope + type.
    """
    # Normalize text (lowercase, strip whitespace)
    normalized = f"{text.lower().strip()}:{scope}:{fact_type}"
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


class FactStore:
    """Store for structured facts with eviction."""

    def __init__(self, conn: AsyncConnection):
        self._conn = conn

    async def ensure_table(self) -> None:
        """Create facts table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute('''
                CREATE TABLE IF NOT EXISTS salient_facts (
                    canonical_id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    scope_type TEXT NOT NULL,
                    scope_id TEXT NOT NULL,
                    fact_type TEXT NOT NULL,
                    source_ts TEXT,
                    text TEXT NOT NULL,
                    confidence REAL DEFAULT 0.8,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            ''')
            await cur.execute('''
                CREATE INDEX IF NOT EXISTS idx_facts_scope
                ON salient_facts (team_id, scope_type, scope_id)
            ''')
            await self._conn.commit()

    async def add_fact(
        self,
        team_id: str,
        scope_type: str,  # "thread", "epic", "channel"
        scope_id: str,    # thread_ts, epic_key, channel_id
        fact: Fact,
    ) -> bool:
        """Add or update a fact.

        Uses UPSERT - updates existing fact if canonical_id matches.
        Applies eviction if scope exceeds limit.

        Returns:
            True if fact was inserted (new), False if updated (existing)
        """
        # Compute canonical ID if not provided
        canonical_id = fact.get("canonical_id") or compute_canonical_id(
            fact["text"], scope_type, fact["type"]
        )

        # UPSERT - insert or update
        async with self._conn.cursor() as cur:
            await cur.execute('''
                INSERT INTO salient_facts (
                    canonical_id, team_id, scope_type, scope_id,
                    fact_type, source_ts, text, confidence
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (canonical_id) DO UPDATE SET
                    text = EXCLUDED.text,
                    confidence = GREATEST(salient_facts.confidence, EXCLUDED.confidence),
                    updated_at = NOW()
            ''', (
                canonical_id, team_id, scope_type, scope_id,
                fact["type"], fact.get("source_ts"), fact["text"],
                fact.get("confidence", 0.8)
            ))

            # Check rowcount to determine if insert happened
            was_insert = cur.rowcount == 1
            await self._conn.commit()

        # Apply eviction if over limit
        limit = FACT_LIMITS.get(scope_type, 100)
        await self._evict_if_needed(team_id, scope_type, scope_id, limit)

        return was_insert

    async def get_facts(
        self,
        team_id: str,
        scope_type: str,
        scope_id: str,
        min_confidence: float = 0.0,
    ) -> list[Fact]:
        """Get facts for scope, ordered by confidence desc."""
        async with self._conn.cursor() as cur:
            await cur.execute('''
                SELECT canonical_id, fact_type, source_ts, text, confidence
                FROM salient_facts
                WHERE team_id = %s AND scope_type = %s AND scope_id = %s
                    AND confidence >= %s
                ORDER BY confidence DESC, updated_at DESC
            ''', (team_id, scope_type, scope_id, min_confidence))
            rows = await cur.fetchall()

        return [
            Fact(
                type=row[1],
                scope=scope_type,
                source_ts=row[2] or "",
                text=row[3],
                confidence=row[4],
                canonical_id=row[0],
            )
            for row in rows
        ]

    async def _evict_if_needed(
        self,
        team_id: str,
        scope_type: str,
        scope_id: str,
        limit: int,
    ) -> int:
        """Evict oldest/lowest confidence facts if over limit.

        Strategy: Delete facts with lowest confidence first,
        then oldest if confidence tied.

        Returns:
            Number of facts evicted
        """
        async with self._conn.cursor() as cur:
            # Count current facts
            await cur.execute('''
                SELECT COUNT(*) FROM salient_facts
                WHERE team_id = %s AND scope_type = %s AND scope_id = %s
            ''', (team_id, scope_type, scope_id))
            row = await cur.fetchone()
            count = row[0] if row else 0

            if count <= limit:
                return 0

            # Delete lowest confidence/oldest facts
            to_delete = count - limit
            await cur.execute('''
                DELETE FROM salient_facts
                WHERE canonical_id IN (
                    SELECT canonical_id FROM salient_facts
                    WHERE team_id = %s AND scope_type = %s AND scope_id = %s
                    ORDER BY confidence ASC, updated_at ASC
                    LIMIT %s
                )
            ''', (team_id, scope_type, scope_id, to_delete))

            evicted = cur.rowcount
            await self._conn.commit()

        if evicted > 0:
            logger.info(f"Evicted {evicted} facts from {scope_type}/{scope_id}")

        return evicted
