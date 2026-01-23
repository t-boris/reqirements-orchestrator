"""Approval policy store for channel-level policy configuration.

Stores per-channel approval policies in PostgreSQL.
Supports configurable policies: any_contributor, only_admins, two_person, role_based.

Phase 27.4 - State-Bound Approvals
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from psycopg import AsyncConnection

from src.schemas.approval import (
    ApprovalPolicy,
    ApprovalRequirement,
    ChannelApprovalConfig,
)

logger = logging.getLogger(__name__)


class ApprovalPolicyStore:
    """PostgreSQL store for channel approval policies.

    Provides CRUD operations for channel-level approval configuration.
    Falls back to ANY_CONTRIBUTOR if no policy is configured.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn

    async def ensure_table(self) -> None:
        """Create approval_policies table if not exists."""
        async with self._conn.cursor() as cur:
            await cur.execute("""
                CREATE TABLE IF NOT EXISTS approval_policies (
                    channel_id TEXT PRIMARY KEY,
                    default_policy TEXT NOT NULL DEFAULT 'any_contributor',
                    requirements JSONB DEFAULT '[]',
                    created_by TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await self._conn.commit()
        logger.debug("Created/verified approval_policies table")

    async def get_policy(self, channel_id: str) -> Optional[ChannelApprovalConfig]:
        """Get approval policy for channel.

        Args:
            channel_id: Slack channel ID

        Returns:
            ChannelApprovalConfig if configured, None otherwise
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                SELECT channel_id, default_policy, requirements, created_by, created_at, updated_at
                FROM approval_policies
                WHERE channel_id = %s
                """,
                (channel_id,),
            )
            row = await cur.fetchone()

        if not row:
            return None

        # Parse requirements from JSONB
        requirements = []
        raw_requirements = row[2] or []
        for req in raw_requirements:
            requirements.append(
                ApprovalRequirement(
                    action_type=req.get("action_type", "jira_create"),
                    policy=ApprovalPolicy(req.get("policy", "any_contributor")),
                    required_role=req.get("required_role"),
                    min_approvers=req.get("min_approvers", 1),
                )
            )

        return ChannelApprovalConfig(
            channel_id=row[0],
            default_policy=ApprovalPolicy(row[1]),
            requirements=requirements,
            created_by=row[3],
            updated_at=row[5].isoformat() if row[5] else datetime.now(timezone.utc).isoformat(),
        )

    async def set_policy(
        self,
        channel_id: str,
        policy: ApprovalPolicy,
        user_id: str,
    ) -> ChannelApprovalConfig:
        """Set default approval policy for channel.

        Uses UPSERT to create or update the policy.

        Args:
            channel_id: Slack channel ID
            policy: Default approval policy
            user_id: User setting the policy

        Returns:
            Updated ChannelApprovalConfig
        """
        now = datetime.now(timezone.utc)
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO approval_policies (channel_id, default_policy, created_by, updated_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (channel_id) DO UPDATE SET
                    default_policy = EXCLUDED.default_policy,
                    updated_at = EXCLUDED.updated_at
                RETURNING channel_id, default_policy, requirements, created_by, created_at, updated_at
                """,
                (channel_id, policy.value, user_id, now),
            )
            row = await cur.fetchone()
            await self._conn.commit()

        logger.info(
            "Set channel approval policy",
            extra={
                "channel_id": channel_id,
                "policy": policy.value,
                "user_id": user_id,
            },
        )

        return ChannelApprovalConfig(
            channel_id=row[0],
            default_policy=ApprovalPolicy(row[1]),
            requirements=[],  # Requirements not updated in this method
            created_by=row[3],
            updated_at=row[5].isoformat() if row[5] else now.isoformat(),
        )

    async def set_requirement(
        self,
        channel_id: str,
        requirement: ApprovalRequirement,
        user_id: str,
    ) -> ChannelApprovalConfig:
        """Set or update an action-specific requirement.

        Adds or updates a requirement in the requirements array.

        Args:
            channel_id: Slack channel ID
            requirement: The requirement to set
            user_id: User setting the requirement

        Returns:
            Updated ChannelApprovalConfig
        """
        now = datetime.now(timezone.utc)

        # First ensure policy exists
        existing = await self.get_policy(channel_id)
        if not existing:
            # Create with default policy first
            await self.set_policy(channel_id, ApprovalPolicy.ANY_CONTRIBUTOR, user_id)

        # Update requirements array
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE approval_policies
                SET requirements = (
                    SELECT jsonb_agg(
                        CASE
                            WHEN elem->>'action_type' = %s THEN %s::jsonb
                            ELSE elem
                        END
                    )
                    FROM (
                        SELECT jsonb_array_elements(
                            COALESCE(requirements, '[]'::jsonb) || %s::jsonb
                        ) AS elem
                    ) sub
                    WHERE NOT EXISTS (
                        SELECT 1 FROM jsonb_array_elements(
                            COALESCE(requirements, '[]'::jsonb)
                        ) AS existing
                        WHERE existing->>'action_type' = %s
                    )
                    OR elem->>'action_type' = %s
                ),
                updated_at = %s
                WHERE channel_id = %s
                """,
                (
                    requirement.action_type,
                    requirement.model_dump_json(),
                    requirement.model_dump_json(),
                    requirement.action_type,
                    requirement.action_type,
                    now,
                    channel_id,
                ),
            )
            await self._conn.commit()

        logger.info(
            "Set channel approval requirement",
            extra={
                "channel_id": channel_id,
                "action_type": requirement.action_type,
                "policy": requirement.policy.value,
            },
        )

        # Return updated config
        return await self.get_policy(channel_id)

    async def get_effective_policy(
        self,
        channel_id: str,
        action_type: str = "jira_create",
    ) -> ApprovalPolicy:
        """Get effective policy for an action, falling back to defaults.

        Checks action-specific requirements first, then falls back
        to channel default, then to global default (ANY_CONTRIBUTOR).

        Args:
            channel_id: Slack channel ID
            action_type: Type of action (jira_create, jira_update, etc.)

        Returns:
            Effective ApprovalPolicy for the action
        """
        config = await self.get_policy(channel_id)
        if not config:
            return ApprovalPolicy.ANY_CONTRIBUTOR

        # Check for specific requirement
        for req in config.requirements:
            if req.action_type == action_type:
                return req.policy

        return config.default_policy

    async def delete_policy(self, channel_id: str) -> bool:
        """Delete approval policy for channel.

        Args:
            channel_id: Slack channel ID

        Returns:
            True if deleted, False if not found
        """
        async with self._conn.cursor() as cur:
            await cur.execute(
                """
                DELETE FROM approval_policies
                WHERE channel_id = %s
                RETURNING channel_id
                """,
                (channel_id,),
            )
            result = await cur.fetchone()
            await self._conn.commit()

        deleted = result is not None
        if deleted:
            logger.info("Deleted channel approval policy", extra={"channel_id": channel_id})
        return deleted
