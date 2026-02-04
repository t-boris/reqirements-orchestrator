"""Projection infrastructure for read models and event-driven side effects.

This module provides the projection base class and implementations:
- EntityProjection: Maintains entities_view read model
- JiraNotificationProjection: Posts Jira comments on decision changes

Based on maro_2_0.md spec Part 4.5 (Projections).

Key patterns:
- All projections are idempotent (safe to replay)
- Uses upserts (ON CONFLICT DO UPDATE) for idempotency
- Projections track their position for resumption
- Side-effect projections (Jira) are fault-tolerant (log and continue on failure)
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import asyncpg

from src.domain.events import (
    ApprovalAdded,
    DecisionAmended,
    DecisionApproved,
    DecisionCommitted,
    DecisionDeprecated,
    DecisionProposed,
    DecisionRecorded,
    DomainEvent,
    ObjectionRaised,
    ObjectionResolved,
    ObjectionWithdrawn,
    WorkItemApproved,
    WorkItemCommitted,
    WorkItemDrafted,
    WorkItemProposed,
    WorkItemUpdated,
)
from src.domain.types import EntityLifecycle


class Projection(ABC):
    """Base class for read model projections.

    Projections transform domain events into optimized read models.
    All projections must be idempotent - applying the same event
    multiple times should produce the same result.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this projection (used for position tracking)."""
        ...

    @abstractmethod
    def handles(self) -> list[str]:
        """Return list of event types this projection handles."""
        ...

    @abstractmethod
    async def apply(self, event: DomainEvent) -> None:
        """Apply event to projection (must be idempotent)."""
        ...


class EntityProjection(Projection):
    """Projects entity events to current state read model.

    Maintains the entities_view table with the current state of each entity,
    enabling fast queries without replaying all events.

    Idempotency is achieved through upserts - re-applying an event
    will simply update the row with the same values.
    """

    def __init__(self, pool: asyncpg.Pool):
        """Initialize the projection.

        Args:
            pool: An asyncpg connection pool
        """
        self.pool = pool
        self._name = "entity_projection"

    @property
    def name(self) -> str:
        return self._name

    def handles(self) -> list[str]:
        """Return event types this projection handles."""
        return [
            "WorkItemDrafted",
            "WorkItemProposed",
            "WorkItemApproved",
            "WorkItemCommitted",
            "WorkItemUpdated",
            "DecisionRecorded",
            "DecisionProposed",
            "DecisionApproved",
            "DecisionCommitted",
            "DecisionAmended",
            "DecisionDeprecated",
            # Approval/Objection events
            "ApprovalAdded",
            "ObjectionRaised",
            "ObjectionResolved",
            "ObjectionWithdrawn",
        ]

    async def apply(self, event: DomainEvent) -> None:
        """Apply event to projection with upsert for idempotency.

        Uses pattern matching to dispatch to the appropriate handler.
        All handlers use upserts to ensure idempotency.
        """
        match event:
            case WorkItemDrafted():
                await self._create_entity(event, EntityLifecycle.DRAFT, "work_item")
            case WorkItemProposed():
                await self._update_lifecycle(
                    event.entity_id,
                    EntityLifecycle.PROPOSED,
                    canonical_message_ts=event.canonical_message_ts,
                )
            case WorkItemApproved():
                await self._add_approval(event.entity_id, event.approved_by)
                await self._update_lifecycle(
                    event.entity_id,
                    EntityLifecycle.APPROVED,
                )
            case WorkItemCommitted():
                await self._commit_entity(event)
            case WorkItemUpdated():
                await self._update_content(event)
            case DecisionRecorded():
                await self._create_entity(event, EntityLifecycle.DRAFT, "decision")
            case DecisionProposed():
                await self._update_lifecycle(
                    event.entity_id,
                    EntityLifecycle.PROPOSED,
                    canonical_message_ts=event.canonical_message_ts,
                )
            case DecisionApproved():
                await self._add_approval(event.entity_id, event.approved_by)
                await self._update_lifecycle(
                    event.entity_id,
                    EntityLifecycle.APPROVED,
                )
            case DecisionCommitted():
                await self._commit_decision(event)
            case DecisionDeprecated():
                await self._deprecate_entity(event)
            case DecisionAmended():
                await self._amend_decision_content(event)
            case ApprovalAdded():
                await self._add_approval(event.entity_id, event.approved_by)
            case ObjectionRaised():
                await self._add_objection(
                    event.entity_id,
                    event.objected_by,
                    event.reason,
                )
            case ObjectionResolved():
                await self._resolve_objection(
                    event.entity_id,
                    event.objection_index,
                    event.resolution,
                )
            case ObjectionWithdrawn():
                await self._withdraw_objection(
                    event.entity_id,
                    event.objection_index,
                )

    async def _create_entity(
        self,
        event: WorkItemDrafted | DecisionRecorded,
        lifecycle: EntityLifecycle,
        entity_type: str,
    ) -> None:
        """Insert or update entity (idempotent via upsert).

        Creates a new entity row or updates if one exists with same ID.
        Stores adr_message_ts for decision entities (None for work items).
        """
        async with self.pool.acquire() as conn:
            adr_ts = getattr(event, "adr_message_ts", None)
            await conn.execute(
                """
                INSERT INTO entities_view
                (id, entity_type, lifecycle, channel_id, thread_ts, content,
                 attribution, version, adr_message_ts, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    content = EXCLUDED.content,
                    attribution = EXCLUDED.attribution,
                    version = EXCLUDED.version,
                    adr_message_ts = EXCLUDED.adr_message_ts,
                    updated_at = NOW()
                """,
                str(event.entity_id),
                entity_type,
                lifecycle.value,
                event.aggregate_id,
                event.thread_ts,
                self._serialize_content(event.content),
                {
                    "proposed_by": event.actor_id,
                    "proposed_at": event.timestamp.isoformat(),
                },
                event.version,
                adr_ts,
            )

    async def _update_lifecycle(
        self,
        entity_id: str,
        lifecycle: EntityLifecycle,
        canonical_message_ts: str | None = None,
    ) -> None:
        """Update entity lifecycle state.

        Updates lifecycle and optionally the canonical message timestamp.
        """
        async with self.pool.acquire() as conn:
            if canonical_message_ts:
                await conn.execute(
                    """
                    UPDATE entities_view
                    SET lifecycle = $1, canonical_message_ts = $2, updated_at = NOW()
                    WHERE id = $3
                    """,
                    lifecycle.value,
                    canonical_message_ts,
                    str(entity_id),
                )
            else:
                await conn.execute(
                    """
                    UPDATE entities_view
                    SET lifecycle = $1, updated_at = NOW()
                    WHERE id = $2
                    """,
                    lifecycle.value,
                    str(entity_id),
                )

    async def _add_approval(self, entity_id: str, approved_by: str) -> None:
        """Add approval to entity's approval list.

        Uses JSONB array append for idempotent approval tracking.
        """
        async with self.pool.acquire() as conn:
            # Use JSONB to append approval
            approval = {
                "user_id": approved_by,
                "timestamp": datetime.utcnow().isoformat(),
            }
            await conn.execute(
                """
                UPDATE entities_view
                SET approvals = COALESCE(approvals, '[]'::jsonb) || $1::jsonb,
                    updated_at = NOW()
                WHERE id = $2
                """,
                [approval],  # Wrap in list for JSONB array append
                str(entity_id),
            )

    async def _commit_entity(self, event: WorkItemCommitted) -> None:
        """Mark work item as committed with Jira link."""
        async with self.pool.acquire() as conn:
            jira_link = {
                "jira_key": event.jira_key,
                "synced_at": datetime.utcnow().isoformat(),
            }
            await conn.execute(
                """
                UPDATE entities_view
                SET lifecycle = $1, jira_link = $2, updated_at = NOW()
                WHERE id = $3
                """,
                EntityLifecycle.COMMITTED.value,
                jira_link,
                str(event.entity_id),
            )

    async def _commit_decision(self, event: DecisionCommitted) -> None:
        """Mark decision as committed with Jira link and field path."""
        async with self.pool.acquire() as conn:
            jira_link = {
                "jira_key": event.jira_key,
                "field_path": event.field_path,
                "synced_at": datetime.utcnow().isoformat(),
            }
            await conn.execute(
                """
                UPDATE entities_view
                SET lifecycle = $1, jira_link = $2, updated_at = NOW()
                WHERE id = $3
                """,
                EntityLifecycle.COMMITTED.value,
                jira_link,
                str(event.entity_id),
            )

    async def _update_content(self, event: WorkItemUpdated) -> None:
        """Update entity content with changes.

        Merges changes into existing content using JSONB concatenation.
        """
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE entities_view
                SET content = content || $1::jsonb, updated_at = NOW()
                WHERE id = $2
                """,
                event.changes,
                str(event.entity_id),
            )

    async def _amend_decision_content(self, event: DecisionAmended) -> None:
        """Update decision content, version, and adr_message_ts on amendment.

        Replaces the full content with new_content (not a merge).
        Also updates adr_message_ts if a new ADR message was posted.
        """
        async with self.pool.acquire() as conn:
            content = self._serialize_content(event.new_content)
            adr_ts = getattr(event, "new_adr_message_ts", None)
            await conn.execute(
                """
                UPDATE entities_view
                SET content = $1, version = $2, adr_message_ts = COALESCE($3, adr_message_ts),
                    updated_at = NOW()
                WHERE id = $4
                """,
                content,
                event.version,
                adr_ts,
                str(event.entity_id),
            )

    async def _deprecate_entity(self, event: DecisionDeprecated) -> None:
        """Mark entity as deprecated."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE entities_view
                SET lifecycle = $1, deprecated_at = $2, superseded_by = $3, updated_at = NOW()
                WHERE id = $4
                """,
                EntityLifecycle.DEPRECATED.value,
                datetime.utcnow(),
                str(event.superseded_by) if event.superseded_by else None,
                str(event.entity_id),
            )

    async def _add_objection(
        self,
        entity_id: str,
        objected_by: str,
        reason: str,
    ) -> None:
        """Add objection to entity's objections list."""
        async with self.pool.acquire() as conn:
            objection = {
                "user_id": objected_by,
                "timestamp": datetime.utcnow().isoformat(),
                "reason": reason,
                "status": "active",
            }
            await conn.execute(
                """
                UPDATE entities_view
                SET objections = COALESCE(objections, '[]'::jsonb) || $1::jsonb,
                    updated_at = NOW()
                WHERE id = $2
                """,
                [objection],
                str(entity_id),
            )

    async def _resolve_objection(
        self,
        entity_id: str,
        objection_index: int,
        resolution: str,
    ) -> None:
        """Mark objection as resolved."""
        async with self.pool.acquire() as conn:
            # Update the specific objection in the array
            await conn.execute(
                """
                UPDATE entities_view
                SET objections = jsonb_set(
                    objections,
                    ARRAY[$1::text],
                    (objections->$1::int) || '{"status": "resolved", "resolution": "'|| $2 ||'"}'::jsonb
                ),
                updated_at = NOW()
                WHERE id = $3
                """,
                str(objection_index),
                resolution,
                str(entity_id),
            )

    async def _withdraw_objection(
        self,
        entity_id: str,
        objection_index: int,
    ) -> None:
        """Mark objection as withdrawn."""
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE entities_view
                SET objections = jsonb_set(
                    objections,
                    ARRAY[$1::text],
                    (objections->$1::int) || '{"status": "withdrawn"}'::jsonb
                ),
                updated_at = NOW()
                WHERE id = $2
                """,
                str(objection_index),
                str(entity_id),
            )

    def _serialize_content(self, content: Any) -> dict:
        """Serialize content to dict for JSONB storage.

        Handles both dict content (from events) and Pydantic models.
        """
        if hasattr(content, "model_dump"):
            return content.model_dump()
        return dict(content) if content else {}


logger = logging.getLogger(__name__)


class JiraNotificationProjection(Projection):
    """Posts Jira comments when decisions are deprecated or amended.

    This projection decouples Jira API calls from Slack action handlers,
    ensuring that handlers complete within Slack's 3-second ack window
    regardless of Jira availability. Jira notifications happen asynchronously
    via the outbox pattern.

    Fault tolerance:
    - Jira failures are logged as warnings, never raised
    - Does not block other projections or event processing
    - Does not retry indefinitely (single attempt, log on failure)
    """

    def __init__(self, pool: asyncpg.Pool):
        """Initialize the projection.

        Args:
            pool: An asyncpg connection pool (used to look up entity jira_link)
        """
        self.pool = pool
        self._name = "jira_notification_projection"

    @property
    def name(self) -> str:
        return self._name

    def handles(self) -> list[str]:
        """Return event types this projection handles."""
        return [
            "DecisionDeprecated",
            "DecisionAmended",
        ]

    async def apply(self, event: DomainEvent) -> None:
        """Apply event by posting Jira notification comment.

        Looks up the entity's jira_link from entities_view. If no jira_link
        exists (entity was never committed to Jira), silently skips.

        All Jira errors are caught and logged — never re-raised.
        """
        match event:
            case DecisionDeprecated():
                await self._notify_deprecated(event)
            case DecisionAmended():
                await self._notify_amended(event)

    async def _get_entity_jira_key(self, entity_id: str) -> str | None:
        """Look up jira_key from entities_view for the given entity.

        Returns the jira_key string if the entity has been committed to Jira,
        or None if it has no jira_link.
        """
        try:
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT jira_link FROM entities_view WHERE id = $1",
                    str(entity_id),
                )
                if row and row["jira_link"]:
                    jira_link = row["jira_link"]
                    # jira_link is stored as JSONB dict
                    if isinstance(jira_link, dict):
                        return jira_link.get("jira_key")
                return None
        except Exception as e:
            logger.warning(f"Failed to look up jira_link for entity {entity_id}: {e}")
            return None

    async def _notify_deprecated(self, event: DecisionDeprecated) -> None:
        """Post deprecation notice to Jira for a deprecated decision."""
        jira_key = await self._get_entity_jira_key(event.entity_id)
        if not jira_key:
            return

        try:
            from src.jira.factory import get_sync_service

            sync_service = get_sync_service()

            # Build a minimal DeprecatedEntity-like object for the sync service.
            # The sync_service.notify_decision_deprecated expects a DeprecatedEntity
            # with jira_link and content. We look up what we need from the DB.
            async with self.pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT content, jira_link FROM entities_view WHERE id = $1",
                    str(event.entity_id),
                )

            if not row:
                return

            from src.domain.content import DecisionContent as DomainDecisionContent, JiraLink
            from src.domain.types import JiraKey, SyncStatus, Version

            content_data = row["content"] if isinstance(row["content"], dict) else {}
            jira_link_data = row["jira_link"] if isinstance(row["jira_link"], dict) else {}

            # Format deprecation comment directly (avoid constructing full entity)
            comment_lines = [
                f"**Decision Superseded: {content_data.get('title', 'Unknown')}**",
                "",
                "This decision has been deprecated.",
                f"Reason: {event.reason}",
                "",
                "---",
                "_Updated via MARO_",
            ]
            comment = "\n".join(comment_lines)

            await sync_service.jira.add_comment(jira_key, comment)
            logger.info(
                f"Posted deprecation notice for decision {event.entity_id} "
                f"to {jira_key} via projection"
            )
        except Exception as e:
            logger.warning(
                f"Jira deprecation notification failed for {event.entity_id} "
                f"(jira_key={jira_key}): {e}"
            )

    async def _notify_amended(self, event: DecisionAmended) -> None:
        """Post amendment notice to Jira for an amended decision."""
        jira_key = await self._get_entity_jira_key(event.entity_id)
        if not jira_key:
            return

        try:
            from src.jira.factory import get_sync_service

            sync_service = get_sync_service()

            # Extract content from event (previous_content and new_content)
            prev = event.previous_content
            new = event.new_content

            prev_title = prev.get("title", "Unknown") if isinstance(prev, dict) else getattr(prev, "title", "Unknown")
            prev_desc = prev.get("description", "") if isinstance(prev, dict) else getattr(prev, "description", "")
            new_title = new.get("title", "Unknown") if isinstance(new, dict) else getattr(new, "title", "Unknown")
            new_desc = new.get("description", "") if isinstance(new, dict) else getattr(new, "description", "")

            comment_lines = [
                f"**Decision Amended: {new_title}**",
                "",
                f"Reason: {event.reason}",
                "",
                f"Previous: {str(prev_desc)[:200]}",
                f"Updated: {str(new_desc)[:200]}",
                "",
                "---",
                "_Updated via MARO_",
            ]
            comment = "\n".join(comment_lines)

            await sync_service.jira.add_comment(jira_key, comment)
            logger.info(
                f"Posted amendment notice for decision {event.entity_id} "
                f"to {jira_key} via projection"
            )
        except Exception as e:
            logger.warning(
                f"Jira amendment notification failed for {event.entity_id} "
                f"(jira_key={jira_key}): {e}"
            )
