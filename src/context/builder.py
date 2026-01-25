"""Context builder for goal-driven context assembly.

Takes ContextSpec, returns ContextPacket with three layers:
- Layer A: Canonical state from DB
- Layer B: Working history with rendered blocks
- Layer C: Retrieval add-ons
"""
import logging
from typing import Optional

from src.context.spec import ContextSpec
from src.context.packet import ContextPacket
from src.context.message_index import MessageIndex, get_message_index
from src.db import get_connection
from src.schemas.intent import SuperMode

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Build context packets from specifications.

    Goal-driven context: ContextSpec determines what gets loaded,
    not "load everything available."
    """

    def __init__(self, message_index: Optional[MessageIndex] = None):
        self._message_index = message_index or get_message_index()

    async def build(self, spec: ContextSpec) -> ContextPacket:
        """Build context packet from specification.

        Args:
            spec: Context specification (mode, target, purpose, budget).

        Returns:
            ContextPacket with assembled context.
        """
        packet = ContextPacket()
        remaining_budget = spec.budget_tokens

        # Layer A: Canonical state (highest priority)
        canonical, tokens_used = await self._build_canonical(spec)
        packet.canonical = canonical
        remaining_budget -= tokens_used
        packet.total_tokens += tokens_used

        # Layer B: Working history
        if spec.include_history and remaining_budget > 500:
            history, tokens_used = await self._build_history(
                spec, budget=remaining_budget
            )
            packet.history = history
            remaining_budget -= tokens_used
            packet.total_tokens += tokens_used

        # Layer C: Retrieval add-ons
        if spec.include_attachments and remaining_budget > 300:
            retrieved, tokens_used = await self._build_retrieved(
                spec, budget=remaining_budget
            )
            packet.retrieved = retrieved
            packet.total_tokens += tokens_used

        # Add header
        packet.header = self._build_header(spec)

        return packet

    def _build_header(self, spec: ContextSpec) -> str:
        """Build context header with mode and purpose."""
        mode_label = spec.mode.value.title()
        return f"[Mode: {mode_label}] Purpose: {spec.purpose}"

    async def _build_canonical(
        self, spec: ContextSpec
    ) -> tuple[str, int]:
        """Build Layer A: Canonical state from DB."""
        parts = []
        tokens = 0

        channel_id = spec.channel_id
        thread_ts = spec.thread_ts

        if not channel_id:
            return "", 0

        async with get_connection() as conn:
            # Load review artifact if required
            if "review_artifact" in spec.required_artifacts:
                from src.db.review_artifact_store import ReviewArtifactStore
                store = ReviewArtifactStore(conn)
                try:
                    await store.create_tables()
                    artifact = await store.get_for_thread(channel_id, thread_ts)
                    if artifact:
                        summary = artifact.updated_summary or artifact.summary
                        parts.append(f"Review ({artifact.kind}): {artifact.topic}")
                        parts.append(summary[:1000])  # Truncate if needed
                except Exception as e:
                    logger.debug(f"Could not load review artifact: {e}")

            # Load channel decisions if required
            if "decisions" in spec.required_artifacts:
                from src.db.decision_store import DecisionStore
                store = DecisionStore(conn)
                try:
                    decisions = await store.list_by_channel(channel_id, limit=5)
                    if decisions:
                        parts.append("Recent decisions:")
                        for dec in decisions:
                            parts.append(f"- {dec.title}: {dec.description[:200]}")
                except Exception as e:
                    logger.debug(f"Could not load decisions: {e}")

        canonical = "\n".join(parts)
        tokens = self._estimate_tokens(canonical)
        return canonical, tokens

    async def _build_history(
        self, spec: ContextSpec, budget: int
    ) -> tuple[str, int]:
        """Build Layer B: Working history with rendered blocks."""
        channel_id = spec.channel_id
        thread_ts = spec.thread_ts

        if not channel_id or not thread_ts:
            return "", 0

        try:
            from src.slack.app import get_slack_client
            from src.slack.history import fetch_thread_history

            client = get_slack_client()
            if not client:
                logger.debug("No Slack client available for history fetch")
                return "", 0

            # Fetch raw messages
            messages = fetch_thread_history(
                client, channel_id, thread_ts
            )

            if not messages:
                return "", 0

            # Limit messages to spec limit
            if len(messages) > spec.history_limit:
                messages = messages[-spec.history_limit:]

            # Normalize with block rendering
            normalized = self._message_index.normalize_batch(messages)

            # Format for context
            lines = []
            for msg in normalized:
                line = msg.to_context_line()
                if line:
                    lines.append(line)

            # Truncate to budget
            history = "\n".join(lines)
            tokens = self._estimate_tokens(history)

            if tokens > budget:
                # Keep most recent messages within budget
                while tokens > budget and lines:
                    lines.pop(0)  # Remove oldest
                    history = "\n".join(lines)
                    tokens = self._estimate_tokens(history)

            return history, tokens

        except Exception as e:
            logger.warning(f"Could not build history: {e}")
            return "", 0

    async def _build_retrieved(
        self, spec: ContextSpec, budget: int
    ) -> tuple[str, int]:
        """Build Layer C: Retrieval add-ons (attachments, Jira)."""
        # Delegate to existing AttachmentRetriever
        # This integrates with Phase 34 attachment system
        try:
            from src.documents.retriever import AttachmentRetriever

            channel_id = spec.channel_id
            thread_ts = spec.thread_ts

            if not channel_id:
                return "", 0

            # Use existing retriever (respects mode policies)
            retriever = AttachmentRetriever(max_total_tokens=budget)
            context = await retriever.get_context(
                channel_id=channel_id,
                thread_ts=thread_ts,
                mode=spec.mode,
            )

            if context:
                prompt_section = context.to_prompt_section()
                if prompt_section:
                    tokens = self._estimate_tokens(prompt_section)
                    return prompt_section, tokens

        except Exception as e:
            logger.debug(f"Could not build retrieved context: {e}")

        return "", 0

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count for text.

        Uses 0.25 tokens per character as rough estimate.
        """
        if not text:
            return 0
        return int(len(text) * 0.25)


# Module-level convenience
async def build_context(spec: ContextSpec) -> ContextPacket:
    """Build context packet from specification.

    Convenience function using default builder.
    """
    builder = ContextBuilder()
    return await builder.build(spec)
