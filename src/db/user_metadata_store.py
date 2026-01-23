"""User metadata store for multi-user support.

Caches Slack user metadata for attribution and display.
Enables looking up display names without repeated API calls.
"""
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field
from psycopg import AsyncConnection


class UserMetadata(BaseModel):
    """Cached Slack user metadata."""

    slack_user_id: str = Field(description="Primary key - Slack user ID")
    team_id: str = Field(description="Slack workspace ID")
    display_name: str = Field(description="Display name at time of capture")
    real_name: Optional[str] = Field(default=None)
    email: Optional[str] = Field(default=None)
    avatar_url: Optional[str] = Field(default=None)
    last_seen_at: datetime = Field(description="Last message timestamp")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserMetadataStore:
    """Async CRUD for user metadata cache.

    Stores Slack user metadata to avoid repeated API calls.
    Updates on each message to keep display names current.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def ensure_table(self) -> None:
        """Create user_metadata table if it doesn't exist."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS user_metadata (
                    slack_user_id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    real_name TEXT,
                    email TEXT,
                    avatar_url TEXT,
                    last_seen_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_metadata_team
                ON user_metadata(team_id)
            """)
            await self._conn.commit()

    async def upsert(
        self,
        slack_user_id: str,
        team_id: str,
        display_name: str,
        *,
        real_name: Optional[str] = None,
        email: Optional[str] = None,
        avatar_url: Optional[str] = None,
    ) -> UserMetadata:
        """Insert or update user metadata.

        Uses UPSERT to update existing records while preserving
        fields that might not be available in every update.

        Args:
            slack_user_id: Slack user ID
            team_id: Slack workspace ID
            display_name: Current display name
            real_name: Optional real name
            email: Optional email (may not be available)
            avatar_url: Optional avatar URL

        Returns:
            The upserted UserMetadata record
        """
        now = datetime.now(timezone.utc)
        async with self._conn.cursor() as cur:
            await cur.execute("""
                INSERT INTO user_metadata
                    (slack_user_id, team_id, display_name, real_name, email, avatar_url, last_seen_at, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (slack_user_id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    real_name = COALESCE(EXCLUDED.real_name, user_metadata.real_name),
                    email = COALESCE(EXCLUDED.email, user_metadata.email),
                    avatar_url = COALESCE(EXCLUDED.avatar_url, user_metadata.avatar_url),
                    last_seen_at = EXCLUDED.last_seen_at,
                    updated_at = EXCLUDED.updated_at
                RETURNING *
            """, (slack_user_id, team_id, display_name, real_name, email, avatar_url, now, now, now))
            row = await cur.fetchone()
            await self._conn.commit()
        return self._row_to_model(row)

    async def get(self, slack_user_id: str) -> Optional[UserMetadata]:
        """Get user metadata by Slack user ID.

        Args:
            slack_user_id: The Slack user ID to look up

        Returns:
            UserMetadata if found, None otherwise
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT * FROM user_metadata WHERE slack_user_id = %s
            """, (slack_user_id,))
            row = await cur.fetchone()
        return self._row_to_model(row) if row else None

    async def get_display_name(self, slack_user_id: str, default: str = "Unknown") -> str:
        """Get display name for formatting.

        Convenience method for attribution formatting.

        Args:
            slack_user_id: The Slack user ID to look up
            default: Default value if user not found

        Returns:
            Display name if found, default otherwise
        """
        user = await self.get(slack_user_id)
        return user.display_name if user else default

    async def get_by_team(self, team_id: str) -> list[UserMetadata]:
        """Get all users for a team.

        Args:
            team_id: The Slack workspace ID

        Returns:
            List of UserMetadata for the team
        """
        async with self._conn.cursor() as cur:
            await cur.execute("""
                SELECT * FROM user_metadata
                WHERE team_id = %s
                ORDER BY last_seen_at DESC
            """, (team_id,))
            rows = await cur.fetchall()
        return [self._row_to_model(row) for row in rows]

    def _row_to_model(self, row: tuple) -> UserMetadata:
        """Convert database row to UserMetadata model.

        Args:
            row: Database row tuple

        Returns:
            UserMetadata instance
        """
        return UserMetadata(
            slack_user_id=row[0],
            team_id=row[1],
            display_name=row[2],
            real_name=row[3],
            email=row[4],
            avatar_url=row[5],
            last_seen_at=row[6],
            created_at=row[7],
            updated_at=row[8],
        )
