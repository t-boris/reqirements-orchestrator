"""Channel context retrieval for agent consumption."""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Literal

from psycopg import AsyncConnection

from src.db.channel_context_store import ChannelContextStore
from src.db.models import (
    ChannelContext,
    ChannelActivitySnapshot,
    EpicSummary,
    WorkItemSummary,
)
from src.config.settings import get_settings

logger = logging.getLogger(__name__)


async def build_channel_snapshot(
    conn: AsyncConnection,
    channel_id: str,
) -> ChannelActivitySnapshot:
    """Build channel activity snapshot from WorkItemStore and JiraRegistry.

    Queries all active WorkItems and registry entries, groups by status/type.

    Args:
        conn: Async database connection.
        channel_id: Slack channel ID.

    Returns:
        ChannelActivitySnapshot with all active items.
    """
    from src.db.workitem_store import WorkItemStore
    from src.db.models import WorkItemStatus, WorkItemType

    store = WorkItemStore(conn)
    await store.create_tables()

    # Get all active work items (not DRAFT status means committed)
    active_statuses = [WorkItemStatus.ACTIVE, WorkItemStatus.DRAFT]
    items = await store.list_by_channel(channel_id, status=active_statuses, limit=500)

    # Group by status
    work_items: dict[str, list[WorkItemSummary]] = {}
    item_counts: dict[str, int] = {}
    active_epics: list[EpicSummary] = []
    recent_tickets: list[str] = []

    for item in items:
        # Track counts by type
        type_name = item.item_type.value
        item_counts[type_name] = item_counts.get(type_name, 0) + 1

        # Build summary
        summary = WorkItemSummary(
            key=item.jira_key or item.id[:8],
            summary=item.summary[:80],
            item_type=type_name,
        )

        # Group by status
        status = item.status.value
        if status not in work_items:
            work_items[status] = []
        work_items[status].append(summary)

        # Track recent tickets (for backward compatibility, use jira_key if available)
        if item.jira_key and len(recent_tickets) < 10:
            recent_tickets.append(item.jira_key)

        # Build epic summaries
        if item.item_type == WorkItemType.EPIC:
            # Count children
            children = await store.get_children(item.id)
            epic = EpicSummary(
                key=item.jira_key or item.id[:8],
                summary=item.summary[:60],
                status=status,
                child_count=len(children),
            )
            active_epics.append(epic)

    # Also include registry entries that aren't in WorkItems
    try:
        from src.db.jira_registry import JiraRegistryStore

        registry = JiraRegistryStore(conn)
        await registry.create_tables()
        registry_items = await registry.get_channel_issues(channel_id, limit=100)

        # Add to recent_tickets if not already there
        for link in registry_items:
            if link.jira_key not in recent_tickets:
                recent_tickets.append(link.jira_key)
                if len(recent_tickets) >= 50:  # Cap at 50 for sanity
                    break

    except Exception as e:
        logger.warning(f"Failed to include registry in snapshot: {e}")

    return ChannelActivitySnapshot(
        active_epics=active_epics,
        recent_tickets=recent_tickets,
        work_items=work_items,
        item_counts=item_counts,
        last_updated=datetime.now(timezone.utc),
    )


class RetrievalMode(str, Enum):
    """Context retrieval modes."""
    COMPACT = "compact"  # 10-20 bullets, production use
    DEBUG = "debug"      # Full details, troubleshooting
    RAW = "raw"          # Internal use, full model


@dataclass
class ContextSource:
    """Tracks where a piece of context came from."""
    layer: Literal["knowledge", "jira", "config", "derived"]
    source_id: str  # pin_id, jira_key, etc.
    source_type: str  # "pin", "epic", "ticket", "config"


@dataclass
class ChannelContextResult:
    """Result of context retrieval for agent consumption.

    Designed for injection into AgentState.
    """
    channel_id: str
    team_id: str

    # Version for cache invalidation
    context_version: int

    # Compact representation (bullets)
    bullets: list[str] = field(default_factory=list)

    # Key facts
    default_project: Optional[str] = None
    naming_convention: Optional[str] = None
    definition_of_done: Optional[str] = None

    # Active context
    active_epics: list[str] = field(default_factory=list)
    recent_tickets: list[str] = field(default_factory=list)

    # Source tracking (for explainability)
    sources: list[ContextSource] = field(default_factory=list)

    # Metadata
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    mode: RetrievalMode = RetrievalMode.COMPACT

    def to_dict(self) -> dict:
        """Convert to dict for AgentState storage."""
        return {
            "channel_id": self.channel_id,
            "team_id": self.team_id,
            "context_version": self.context_version,
            "bullets": self.bullets,
            "default_project": self.default_project,
            "naming_convention": self.naming_convention,
            "definition_of_done": self.definition_of_done,
            "active_epics": self.active_epics,
            "recent_tickets": self.recent_tickets,
            "retrieved_at": self.retrieved_at.isoformat(),
            "mode": self.mode.value,
        }


class ChannelContextRetriever:
    """Retrieves and compresses channel context for agent consumption.

    Usage:
        async with get_connection() as conn:
            retriever = ChannelContextRetriever(conn)
            result = await retriever.get_context(team_id, channel_id, mode="compact")
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn
        self._store = ChannelContextStore(conn)

    async def get_context(
        self,
        team_id: str,
        channel_id: str,
        mode: RetrievalMode = RetrievalMode.COMPACT,
    ) -> ChannelContextResult:
        """Get channel context in specified mode.

        Args:
            team_id: Slack team ID.
            channel_id: Slack channel ID.
            mode: Retrieval mode (compact, debug, raw).

        Returns:
            ChannelContextResult with compressed context.
        """
        ctx = await self._store.get_by_channel(team_id, channel_id)

        if not ctx:
            # Return empty context for new channels
            return ChannelContextResult(
                channel_id=channel_id,
                team_id=team_id,
                context_version=0,
                mode=mode,
            )

        if mode == RetrievalMode.RAW:
            return self._to_raw_result(ctx)
        elif mode == RetrievalMode.DEBUG:
            return self._to_debug_result(ctx)
        else:
            return self._to_compact_result(ctx)

    def _to_compact_result(self, ctx: ChannelContext) -> ChannelContextResult:
        """Convert to compact mode (10-20 bullets max)."""
        settings = get_settings()
        max_bullets = settings.channel_context_max_bullets

        bullets = []
        sources = []

        # Layer 1: Config (defaults)
        if ctx.config.default_jira_project:
            bullets.append(f"Default project: {ctx.config.default_jira_project}")
            sources.append(ContextSource("config", "default_project", "config"))

        # Layer 2: Knowledge (facts from pins)
        if ctx.knowledge.naming_convention:
            bullets.append(f"Naming: {ctx.knowledge.naming_convention[:80]}")
            sources.append(ContextSource("knowledge", ctx.knowledge.source_pin_ids[0] if ctx.knowledge.source_pin_ids else "", "pin"))

        if ctx.knowledge.definition_of_done:
            bullets.append(f"DoD: {ctx.knowledge.definition_of_done[:80]}")

        if ctx.knowledge.api_format_rules:
            bullets.append(f"API rules: {ctx.knowledge.api_format_rules[:60]}")

        # Custom rules (max 3)
        for name, rule in list(ctx.knowledge.custom_rules.items())[:3]:
            bullets.append(f"{name}: {rule[:50]}")

        # Layer 3: Activity (enhanced for Rule 15)
        if ctx.activity.active_epics:
            # Handle both EpicSummary objects and legacy string format
            epic_keys = []
            for epic in ctx.activity.active_epics[:5]:
                if isinstance(epic, EpicSummary):
                    epic_keys.append(epic.key)
                    sources.append(ContextSource("jira", epic.key, "epic"))
                elif isinstance(epic, dict):
                    key = epic.get("key", str(epic))
                    epic_keys.append(key)
                    sources.append(ContextSource("jira", key, "epic"))
                else:
                    epic_keys.append(str(epic))
                    sources.append(ContextSource("jira", str(epic), "epic"))
            epics_str = ", ".join(epic_keys)
            bullets.append(f"Active epics: {epics_str}")

        # Include item counts if available (Rule 15 enhancement)
        if ctx.activity.item_counts:
            counts_parts = []
            for item_type, count in ctx.activity.item_counts.items():
                counts_parts.append(f"{count} {item_type}(s)")
            if counts_parts:
                bullets.append(f"Work items: {', '.join(counts_parts)}")

        if ctx.activity.recent_tickets:
            tickets_str = ", ".join(ctx.activity.recent_tickets[:10])  # Increased from 5
            bullets.append(f"Recent tickets: {tickets_str}")

        # Truncate to max
        bullets = bullets[:max_bullets]

        # Convert active_epics to keys for backward compatibility
        active_epic_keys = []
        for epic in ctx.activity.active_epics[:10]:
            if isinstance(epic, EpicSummary):
                active_epic_keys.append(epic.key)
            elif isinstance(epic, dict):
                active_epic_keys.append(epic.get("key", str(epic)))
            else:
                active_epic_keys.append(str(epic))

        return ChannelContextResult(
            channel_id=ctx.channel_id,
            team_id=ctx.team_id,
            context_version=ctx.version,
            bullets=bullets,
            default_project=ctx.config.default_jira_project,
            naming_convention=ctx.knowledge.naming_convention,
            definition_of_done=ctx.knowledge.definition_of_done,
            active_epics=active_epic_keys,
            recent_tickets=ctx.activity.recent_tickets[:50],  # Increased from 10 (Rule 15)
            sources=sources,
            mode=RetrievalMode.COMPACT,
        )

    def _to_debug_result(self, ctx: ChannelContext) -> ChannelContextResult:
        """Convert to debug mode (full details)."""
        result = self._to_compact_result(ctx)
        result.mode = RetrievalMode.DEBUG

        # Add all bullets without truncation
        result.bullets = []

        # Full config
        result.bullets.append(f"[CONFIG] default_project: {ctx.config.default_jira_project}")
        result.bullets.append(f"[CONFIG] trigger_rule: {ctx.config.trigger_rule}")
        result.bullets.append(f"[CONFIG] epic_binding: {ctx.config.epic_binding_behavior}")

        # Full knowledge
        if ctx.knowledge.naming_convention:
            result.bullets.append(f"[KNOWLEDGE] naming: {ctx.knowledge.naming_convention}")
        if ctx.knowledge.definition_of_done:
            result.bullets.append(f"[KNOWLEDGE] DoD: {ctx.knowledge.definition_of_done}")
        if ctx.knowledge.api_format_rules:
            result.bullets.append(f"[KNOWLEDGE] API: {ctx.knowledge.api_format_rules}")
        for name, rule in ctx.knowledge.custom_rules.items():
            result.bullets.append(f"[KNOWLEDGE] {name}: {rule}")

        # Full activity
        result.bullets.append(f"[ACTIVITY] epics: {ctx.activity.active_epics}")
        result.bullets.append(f"[ACTIVITY] tickets: {ctx.activity.recent_tickets}")

        # Metadata
        result.bullets.append(f"[META] version: {ctx.version}")
        result.bullets.append(f"[META] pinned_digest: {ctx.pinned_digest}")
        result.bullets.append(f"[META] updated_at: {ctx.updated_at}")

        return result

    def _to_raw_result(self, ctx: ChannelContext) -> ChannelContextResult:
        """Convert to raw mode (for internal use)."""
        result = self._to_debug_result(ctx)
        result.mode = RetrievalMode.RAW
        return result

    async def get_work_snapshot(
        self,
        channel_id: str,
    ) -> ChannelActivitySnapshot:
        """Get full work snapshot for a channel (Rule 15 enhancement).

        Builds snapshot from WorkItemStore and JiraRegistry,
        including ALL active items (not just last 10).

        Args:
            channel_id: Slack channel ID.

        Returns:
            ChannelActivitySnapshot with all active items.
        """
        return await build_channel_snapshot(self._conn, channel_id)
