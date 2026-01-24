"""Thread context resolution service.

Implements Rule A3: Context Inheritance from Phase 33 - Anchor Message Architecture.
Messages in a thread automatically inherit the object_id of the anchor.

This service provides unified thread-to-object resolution. When a message arrives
in a thread, it determines what object (Decision, WorkItem, etc.) the thread
is managing.
"""

import logging
from typing import Optional
from uuid import UUID

from src.db.anchor_store import AnchorStore
from src.db.decision_store import DecisionStore
from src.db.workitem_store import WorkItemStore
from src.schemas.anchor import AnchorMessage, AnchorType, ThreadContext
from src.slack.thread_bindings import ThreadBindingStore

logger = logging.getLogger(__name__)


class ContextResolver:
    """Resolves what object a thread is managing.

    Resolution order (first match wins):
    1. AnchorStore - check if thread_ts is an anchor message
    2. DecisionStore - check for decision canonical message
    3. WorkItemStore - check for workitem source thread
    4. ThreadBindingStore - legacy Jira key binding

    This multi-tier approach ensures backward compatibility while
    supporting the new anchor-based pattern.

    Usage:
        async with get_connection() as conn:
            resolver = ContextResolver(
                anchor_store=AnchorStore(conn),
                decision_store=DecisionStore(conn),
                workitem_store=WorkItemStore(conn),
                binding_store=ThreadBindingStore(conn),
            )
            ctx = await resolver.resolve(channel_id, thread_ts, hydrate=True)
    """

    def __init__(
        self,
        anchor_store: AnchorStore,
        decision_store: DecisionStore,
        workitem_store: WorkItemStore,
        binding_store: ThreadBindingStore,
    ) -> None:
        """Initialize resolver with all required stores.

        Args:
            anchor_store: AnchorStore for anchor message lookups.
            decision_store: DecisionStore for decision canonical message lookups.
            workitem_store: WorkItemStore for workitem source thread lookups.
            binding_store: ThreadBindingStore for legacy Jira key bindings.
        """
        self._anchor_store = anchor_store
        self._decision_store = decision_store
        self._workitem_store = workitem_store
        self._binding_store = binding_store

    async def resolve(
        self,
        channel_id: str,
        thread_ts: str,
        hydrate: bool = False,
    ) -> Optional[ThreadContext]:
        """Resolve thread to its managing object.

        Implements the multi-tier resolution strategy:
        1. Check AnchorStore (new anchor pattern)
        2. Check DecisionStore (existing canonical message pattern)
        3. Check WorkItemStore (workitem source thread)
        4. Check ThreadBindingStore (legacy Jira key binding)

        Args:
            channel_id: Slack channel ID.
            thread_ts: Thread timestamp (parent message ts).
            hydrate: If True, load full entity into context.

        Returns:
            ThreadContext if thread is anchored to an object, None otherwise.
        """
        # 1. Check AnchorStore (new pattern - Phase 33)
        anchor = await self._anchor_store.get_by_message(channel_id, thread_ts)
        if anchor:
            logger.debug(
                "Resolved thread context from AnchorStore",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "anchor_type": anchor.anchor_type.value,
                    "object_id": anchor.object_id,
                },
            )
            ctx = ThreadContext(
                anchor_type=anchor.anchor_type,
                object_id=anchor.object_id,
                anchor_message_ts=anchor.message_ts,
            )
            if hydrate:
                await self._hydrate_context(ctx)
            return ctx

        # 2. Check DecisionStore (existing canonical message pattern)
        decision = await self._decision_store.get_by_canonical_message(
            channel_id, thread_ts
        )
        if decision:
            logger.debug(
                "Resolved thread context from DecisionStore",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "decision_id": decision.id,
                },
            )
            return ThreadContext(
                anchor_type=AnchorType.DECISION,
                object_id=str(decision.id),
                anchor_message_ts=thread_ts,
                decision=decision if hydrate else None,
            )

        # 3. Check WorkItemStore (workitem source thread)
        # WorkItems track their source thread via source_thread_ts
        workitem = await self._get_workitem_by_source_thread(channel_id, thread_ts)
        if workitem:
            logger.debug(
                "Resolved thread context from WorkItemStore",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "workitem_id": workitem.id,
                    "jira_key": workitem.jira_key,
                },
            )
            return ThreadContext(
                anchor_type=AnchorType.WORKITEM,
                object_id=str(workitem.id),
                anchor_message_ts=thread_ts,
                workitem=workitem if hydrate else None,
                jira_key=workitem.jira_key,
            )

        # 4. Check legacy ThreadBindingStore (Jira key bindings)
        binding = await self._binding_store.get_binding(channel_id, thread_ts)
        if binding:
            logger.debug(
                "Resolved thread context from ThreadBindingStore (legacy)",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "issue_key": binding.issue_key,
                },
            )
            return ThreadContext(
                anchor_type=AnchorType.WORKITEM,  # Legacy bindings are Jira-based
                object_id=binding.issue_key,
                anchor_message_ts=thread_ts,
                jira_key=binding.issue_key,
            )

        # No context found
        logger.debug(
            "No thread context found",
            extra={
                "channel_id": channel_id,
                "thread_ts": thread_ts,
            },
        )
        return None

    async def _get_workitem_by_source_thread(
        self,
        channel_id: str,
        thread_ts: str,
    ):
        """Get workitem by its source thread.

        WorkItems don't have a dedicated canonical_message_ts field,
        but they do track source_thread_ts which is the thread where
        the workitem was created.

        Args:
            channel_id: Slack channel ID.
            thread_ts: Thread timestamp to search for.

        Returns:
            WorkItem if found, None otherwise.
        """
        # Query workitems in this channel that have this source_thread_ts
        # We need to check if WorkItemStore has such a query method
        # For now, we'll query by channel and filter
        try:
            from src.db.models import WorkItemStatus

            # Get all active workitems in channel and filter by source_thread_ts
            # This is not the most efficient, but workitem counts are typically small
            items = await self._workitem_store.list_by_channel(
                channel_id,
                status=[WorkItemStatus.DRAFT, WorkItemStatus.ACTIVE],
                limit=100,
            )
            for item in items:
                if item.source_thread_ts == thread_ts:
                    return item
        except Exception as e:
            logger.warning(f"Failed to query workitems by source thread: {e}")

        return None

    async def _hydrate_context(self, ctx: ThreadContext) -> None:
        """Load full entity into context.

        Populates the decision or workitem field based on anchor_type.

        Args:
            ctx: ThreadContext to hydrate (modified in place).
        """
        try:
            if ctx.anchor_type == AnchorType.DECISION:
                ctx.decision = await self._decision_store.get(ctx.object_id)
            elif ctx.anchor_type == AnchorType.WORKITEM:
                # Try to parse as UUID first
                try:
                    UUID(ctx.object_id)
                    ctx.workitem = await self._workitem_store.get(ctx.object_id)
                    if ctx.workitem:
                        ctx.jira_key = ctx.workitem.jira_key
                except ValueError:
                    # Not a UUID - might be a Jira key from legacy binding
                    # Try to get workitem by jira_key
                    ctx.workitem = await self._workitem_store.get_by_jira_key(
                        ctx.object_id
                    )
                    if ctx.workitem:
                        ctx.jira_key = ctx.workitem.jira_key
                    else:
                        # Legacy binding with no local workitem
                        ctx.jira_key = ctx.object_id
        except Exception as e:
            logger.warning(f"Failed to hydrate context: {e}")


# =============================================================================
# Convenience function for single-use resolution
# =============================================================================


async def resolve_thread_context(
    channel_id: str,
    thread_ts: str,
    hydrate: bool = False,
) -> Optional[ThreadContext]:
    """Resolve thread context with automatic connection management.

    Convenience wrapper that manages database connection internally.
    For batch operations, use ContextResolver directly with a shared connection.

    Args:
        channel_id: Slack channel ID.
        thread_ts: Thread timestamp (parent message ts).
        hydrate: If True, load full entity into context.

    Returns:
        ThreadContext if thread is anchored to an object, None otherwise.
    """
    from src.db import get_connection

    async with get_connection() as conn:
        resolver = ContextResolver(
            anchor_store=AnchorStore(conn),
            decision_store=DecisionStore(conn),
            workitem_store=WorkItemStore(conn),
            binding_store=ThreadBindingStore(conn),
        )
        return await resolver.resolve(channel_id, thread_ts, hydrate=hydrate)
