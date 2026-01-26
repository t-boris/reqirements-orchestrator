"""Architecture Reference Resolver.

When user says "create Epics based on the architecture", we need to resolve
what "the architecture" refers to:

1. Thread bound to pinned Decision/Baseline -> use artifact_id
2. Recent messages contain "Architecture Decision:" -> collect them
3. Channel has stored decisions in channel_decisions -> use those
4. Else -> ask user

Fix C: Proper resolution of architecture references.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from psycopg import AsyncConnection

logger = logging.getLogger(__name__)


@dataclass
class ReferenceBundle:
    """Resolved architecture reference content."""

    # Source type
    source: str  # "artifact", "thread_decisions", "channel_decisions", "none"

    # Content
    decisions: list[dict] = field(default_factory=list)  # {title, description}
    artifact_id: Optional[str] = None
    artifact_summary: Optional[str] = None

    # Metadata
    decision_count: int = 0
    source_description: str = ""

    def is_empty(self) -> bool:
        """Check if bundle has any content."""
        return not self.decisions and not self.artifact_summary

    def to_context_string(self) -> str:
        """Format as context for LLM prompt."""
        if self.artifact_summary:
            return f"=== Architecture (from {self.source}) ===\n{self.artifact_summary}\n=== End Architecture ==="

        if self.decisions:
            parts = [f"=== Architecture Decisions ({self.decision_count} items) ==="]
            for d in self.decisions[:15]:  # Limit to 15
                title = d.get("title", "Untitled")
                desc = d.get("description", "")
                parts.append(f"• {title}")
                if desc:
                    parts.append(f"  {desc[:200]}")
            parts.append("=== End Decisions ===")
            return "\n".join(parts)

        return ""


def _extract_text_from_blocks(blocks: list[dict]) -> str:
    """Extract text content from Slack blocks.

    Slack bot messages often have empty text but content in blocks.
    This extracts readable text from section blocks.

    Args:
        blocks: Slack message blocks

    Returns:
        Extracted text content
    """
    if not blocks:
        return ""

    parts = []
    for block in blocks:
        block_type = block.get("type", "")

        if block_type == "section":
            text_obj = block.get("text", {})
            if isinstance(text_obj, dict):
                text = text_obj.get("text", "")
                if text:
                    parts.append(text)
            elif isinstance(text_obj, str):
                parts.append(text_obj)

            # Also check fields
            fields = block.get("fields", [])
            for field in fields:
                if isinstance(field, dict):
                    parts.append(field.get("text", ""))

        elif block_type == "context":
            elements = block.get("elements", [])
            for elem in elements:
                if isinstance(elem, dict):
                    parts.append(elem.get("text", ""))

        elif block_type == "rich_text":
            # Rich text has nested structure
            elements = block.get("elements", [])
            for section in elements:
                if section.get("type") == "rich_text_section":
                    for elem in section.get("elements", []):
                        if elem.get("type") == "text":
                            parts.append(elem.get("text", ""))

    return "\n".join(p for p in parts if p)


def _find_decisions_in_messages(messages: list[dict]) -> list[dict]:
    """Extract architecture decisions from message list.

    Looks for patterns like:
    - "Architecture Decision: ..."
    - "Decision: ..."
    - Messages from bot containing decision summaries

    Args:
        messages: List of message dicts with text/blocks

    Returns:
        List of {title, description} dicts
    """
    decisions = []
    decision_pattern = re.compile(
        r"(?:architecture\s+)?decision\s*(?:\d+)?[:\-]\s*(.+)",
        re.IGNORECASE,
    )

    for msg in messages:
        # Get text content - try blocks first, then text field
        blocks = msg.get("blocks", [])
        text = msg.get("text", "")

        if blocks:
            extracted = _extract_text_from_blocks(blocks)
            if extracted:
                text = extracted

        if not text:
            continue

        # Look for decision patterns
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            match = decision_pattern.match(line)
            if match:
                decision_text = match.group(1).strip()
                # Split into title and description if long
                if len(decision_text) > 100:
                    title = decision_text[:80] + "..."
                    description = decision_text
                else:
                    title = decision_text
                    description = ""

                decisions.append({
                    "title": title,
                    "description": description,
                    "source_ts": msg.get("ts", ""),
                })

        # Also check for structured decision format in bot messages
        if msg.get("bot_id") or msg.get("subtype") == "bot_message":
            # Check for "Topic:" and "Decision:" patterns (from approve_architecture)
            topic_match = re.search(r"\*?Topic\*?[:\s]+(.+?)(?:\n|$)", text)
            decision_match = re.search(r"\*?Decision\*?[:\s]+(.+?)(?:\n|$)", text)

            if topic_match and decision_match:
                decisions.append({
                    "title": topic_match.group(1).strip(),
                    "description": decision_match.group(1).strip(),
                    "source_ts": msg.get("ts", ""),
                })

    return decisions


async def resolve_architecture_reference(
    conn: AsyncConnection,
    channel_id: str,
    thread_ts: str,
    conversation_messages: list[dict] | None = None,
) -> ReferenceBundle:
    """Resolve what "the architecture" refers to in current context.

    Priority:
    1. Thread bound to pinned artifact -> use artifact
    2. Recent messages contain decision patterns -> collect them
    3. Channel has stored decisions -> use those
    4. Nothing found -> return empty bundle

    Args:
        conn: Database connection
        channel_id: Slack channel ID
        thread_ts: Thread timestamp
        conversation_messages: Optional pre-fetched conversation messages

    Returns:
        ReferenceBundle with resolved content or empty bundle
    """
    bundle = ReferenceBundle(source="none")

    # Priority 1: Check for bound artifact
    try:
        from src.db.artifact_store import ArtifactStore

        artifact_store = ArtifactStore(conn)
        # Get artifacts for this thread
        artifacts = await artifact_store.get_by_thread(channel_id, thread_ts)

        if artifacts:
            # Use most recent approved artifact
            for artifact in artifacts:
                if artifact.approved_at:
                    content = artifact.updated_summary or artifact.summary or artifact.full_content
                    bundle = ReferenceBundle(
                        source="artifact",
                        artifact_id=artifact.artifact_id,
                        artifact_summary=content[:3000] if content else "",
                        decision_count=1,
                        source_description=f"Approved {artifact.kind.value} review",
                    )
                    logger.info(f"Resolved reference to artifact {artifact.artifact_id}")
                    return bundle

    except Exception as e:
        logger.warning(f"Failed to check artifacts: {e}")

    # Priority 2: Check conversation messages for decision patterns
    if conversation_messages:
        decisions = _find_decisions_in_messages(conversation_messages)
        if decisions:
            bundle = ReferenceBundle(
                source="thread_decisions",
                decisions=decisions,
                decision_count=len(decisions),
                source_description=f"Found {len(decisions)} decision(s) in thread",
            )
            logger.info(f"Resolved reference to {len(decisions)} thread decisions")
            return bundle

    # Priority 3: Check channel_decisions table
    try:
        query = """
            SELECT decision_ts, topic, decision_text, created_at
            FROM channel_decisions
            WHERE channel_id = %s
            ORDER BY created_at DESC
            LIMIT 20
        """
        async with conn.cursor() as cur:
            await cur.execute(query, [channel_id])
            rows = await cur.fetchall()

        if rows:
            decisions = [
                {
                    "title": row[1] or "Untitled",
                    "description": (row[2] or "")[:300],
                    "source_ts": row[0],
                }
                for row in rows
            ]
            bundle = ReferenceBundle(
                source="channel_decisions",
                decisions=decisions,
                decision_count=len(decisions),
                source_description=f"Found {len(decisions)} stored decision(s) in channel",
            )
            logger.info(f"Resolved reference to {len(decisions)} channel decisions")
            return bundle

    except Exception as e:
        logger.warning(f"Failed to check channel_decisions: {e}")

    # Priority 4: Nothing found
    logger.info("No architecture reference found")
    return bundle


async def get_reference_bundle_for_extraction(
    conn: AsyncConnection,
    channel_id: str,
    thread_ts: str,
    conversation_context: dict | None = None,
) -> ReferenceBundle:
    """Get reference bundle for use in extraction prompt.

    Wrapper that extracts messages from conversation_context
    and calls resolve_architecture_reference.

    Args:
        conn: Database connection
        channel_id: Slack channel ID
        thread_ts: Thread timestamp
        conversation_context: Optional conversation context dict

    Returns:
        ReferenceBundle with resolved content
    """
    messages = []
    if conversation_context:
        messages = conversation_context.get("messages", [])

    return await resolve_architecture_reference(
        conn=conn,
        channel_id=channel_id,
        thread_ts=thread_ts,
        conversation_messages=messages,
    )
