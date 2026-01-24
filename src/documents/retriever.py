"""Attachment retriever with intent-scoped policies.

Determines what attachment content to include based on SuperMode.
Never includes whole files — only summaries, pinned content, or top-K chunks.

Anti-pattern avoided: Including whole file in prompt.

Intent-scoped rules:
| Mode    | Attachment Policy                              |
|---------|------------------------------------------------|
| CHAT    | Don't include. Offer: "I see an attachment..." |
| THINK   | Pinned auto + top-K chunks if retrieval high   |
| BUILD   | Pinned auto + structural (requirements, AC)    |
| OPERATE | Only logs, JSON, stacktraces — via retrieval   |
| DECIDE  | Pinned + cited chunks with source refs         |
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from uuid import UUID

from src.db.attachment_chunk_store import AttachmentChunkStore
from src.db.attachment_store import AttachmentStore
from src.db import get_connection
from src.schemas.attachment import Attachment, AttachmentStatus
from src.schemas.intent import SuperMode

logger = logging.getLogger(__name__)


class AttachmentPolicy(str, Enum):
    """Attachment inclusion policies by mode."""
    NONE = "none"                    # Don't include, offer to use
    PINNED_ONLY = "pinned_only"      # Only pinned attachments
    PINNED_RETRIEVAL = "pinned+retrieval"  # Pinned + top-K chunks
    PINNED_STRUCTURAL = "pinned+structural"  # Pinned + requirements/AC
    LOGS_RETRIEVAL = "logs_retrieval"  # Only logs/stacktraces
    PINNED_CITED = "pinned+cited"    # Pinned + source citations


# Policy mapping by SuperMode
MODE_POLICIES: dict[SuperMode, AttachmentPolicy] = {
    SuperMode.CHAT: AttachmentPolicy.NONE,
    SuperMode.THINK: AttachmentPolicy.PINNED_RETRIEVAL,
    SuperMode.BUILD: AttachmentPolicy.PINNED_STRUCTURAL,
    SuperMode.OPERATE: AttachmentPolicy.LOGS_RETRIEVAL,
    SuperMode.DECIDE: AttachmentPolicy.PINNED_CITED,
}


@dataclass
class AttachmentContext:
    """Resolved attachment context for prompt injection.

    Attributes:
        pinned: Summaries of pinned attachments.
        retrieved_chunks: Top-K relevant chunks.
        offer_available: Attachments available but not included.
        sources: Source references for citations.
        total_tokens: Estimated token count of included content.
    """
    pinned: list[dict] = field(default_factory=list)
    retrieved_chunks: list[dict] = field(default_factory=list)
    offer_available: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    total_tokens: int = 0

    def to_prompt_section(self) -> str:
        """Format as prompt section.

        Returns:
            Formatted string for prompt injection.
        """
        parts = []

        if self.pinned:
            parts.append("## Pinned Attachments\n")
            for p in self.pinned:
                parts.append(f"### {p['filename']}\n{p['content']}\n")

        if self.retrieved_chunks:
            parts.append("## Relevant Document Sections\n")
            for c in self.retrieved_chunks:
                parts.append(
                    f"*From {c['filename']} (section {c['chunk_index']}):*\n"
                    f"{c['content']}\n"
                )

        return "\n".join(parts)

    def to_offer_message(self) -> Optional[str]:
        """Format message offering to use available attachments.

        Returns:
            Offer message or None if no attachments available.
        """
        if not self.offer_available:
            return None

        names = [a["filename"] for a in self.offer_available[:3]]
        if len(self.offer_available) > 3:
            names.append(f"+{len(self.offer_available) - 3} more")

        return (
            f":paperclip: I see {len(self.offer_available)} attachment(s): "
            f"{', '.join(names)}. "
            f"Would you like me to use them? "
            f"You can pin them with the button above."
        )


class AttachmentRetriever:
    """Retrieves attachment context based on intent policy.

    Usage:
        retriever = AttachmentRetriever()
        context = await retriever.get_context(
            channel_id="C123",
            thread_ts="123.456",
            mode=SuperMode.BUILD,
            query="user requirements",
        )
        prompt_section = context.to_prompt_section()
    """

    def __init__(
        self,
        max_pinned_tokens: int = 2000,
        max_retrieval_tokens: int = 1500,
        top_k_chunks: int = 5,
    ) -> None:
        """Initialize retriever.

        Args:
            max_pinned_tokens: Token budget for pinned content.
            max_retrieval_tokens: Token budget for retrieved chunks.
            top_k_chunks: Number of chunks to retrieve.
        """
        self.max_pinned_tokens = max_pinned_tokens
        self.max_retrieval_tokens = max_retrieval_tokens
        self.top_k_chunks = top_k_chunks

    async def get_context(
        self,
        channel_id: str,
        thread_ts: Optional[str],
        mode: SuperMode,
        query: Optional[str] = None,
    ) -> AttachmentContext:
        """Get attachment context for a request.

        Args:
            channel_id: Slack channel.
            thread_ts: Thread timestamp (scope to thread attachments).
            mode: SuperMode determining policy.
            query: User query for retrieval relevance.

        Returns:
            AttachmentContext with content based on policy.
        """
        policy = MODE_POLICIES.get(mode, AttachmentPolicy.NONE)
        context = AttachmentContext()

        # Get all ready attachments in scope
        async with get_connection() as conn:
            store = AttachmentStore(conn)
            attachments = await store.list_by_channel(
                channel_id=channel_id,
                thread_ts=thread_ts,
                status=AttachmentStatus.READY,
            )

        if not attachments:
            return context

        # Apply policy
        if policy == AttachmentPolicy.NONE:
            # Don't include, but offer available
            context.offer_available = [
                {"filename": a.filename, "id": str(a.id)}
                for a in attachments
            ]

        elif policy in (
            AttachmentPolicy.PINNED_ONLY,
            AttachmentPolicy.PINNED_RETRIEVAL,
            AttachmentPolicy.PINNED_STRUCTURAL,
            AttachmentPolicy.PINNED_CITED,
        ):
            # Include pinned attachments
            pinned = [a for a in attachments if a.pinned]
            context.pinned = await self._resolve_pinned(pinned)
            context.total_tokens += sum(
                p.get("tokens", 0) for p in context.pinned
            )

            # Add retrieval for non-pinned if policy allows
            if policy in (
                AttachmentPolicy.PINNED_RETRIEVAL,
                AttachmentPolicy.PINNED_STRUCTURAL,
                AttachmentPolicy.PINNED_CITED,
            ) and query:
                unpinned = [a for a in attachments if not a.pinned]
                if unpinned:
                    chunks = await self._retrieve_chunks(
                        [a.id for a in unpinned],
                        query,
                    )
                    context.retrieved_chunks = chunks
                    context.total_tokens += sum(
                        c.get("tokens", 0) for c in chunks
                    )

            # Track sources for citations
            if policy == AttachmentPolicy.PINNED_CITED:
                context.sources = [
                    {"filename": a.filename, "id": str(a.id)}
                    for a in pinned
                ]

            # Offer remaining
            used_ids = {p["id"] for p in context.pinned}
            used_ids.update(c["attachment_id"] for c in context.retrieved_chunks)
            context.offer_available = [
                {"filename": a.filename, "id": str(a.id)}
                for a in attachments
                if str(a.id) not in used_ids
            ]

        elif policy == AttachmentPolicy.LOGS_RETRIEVAL:
            # Only include logs/stacktraces via retrieval
            if query:
                log_attachments = [
                    a for a in attachments
                    if self._is_log_type(a)
                ]
                if log_attachments:
                    chunks = await self._retrieve_chunks(
                        [a.id for a in log_attachments],
                        query,
                    )
                    context.retrieved_chunks = chunks

        return context

    async def _resolve_pinned(
        self,
        attachments: list[Attachment],
    ) -> list[dict]:
        """Resolve pinned attachments to includable content.

        Uses summary + limited extracted text.
        """
        result = []
        remaining_tokens = self.max_pinned_tokens

        for attachment in attachments:
            if remaining_tokens <= 0:
                break

            # Use summary if available, else truncated text
            content = attachment.summary or ""
            if attachment.extracted_text and remaining_tokens > 500:
                # Include some text beyond summary
                text_budget = min(remaining_tokens - 200, 1000)
                content += f"\n\n{attachment.extracted_text[:text_budget * 4]}"

            tokens = len(content) // 4
            remaining_tokens -= tokens

            result.append({
                "filename": attachment.filename,
                "id": str(attachment.id),
                "content": content,
                "tokens": tokens,
            })

        return result

    async def _retrieve_chunks(
        self,
        attachment_ids: list[UUID],
        query: str,
    ) -> list[dict]:
        """Retrieve relevant chunks via full-text search."""
        async with get_connection() as conn:
            chunk_store = AttachmentChunkStore(conn)
            results = await chunk_store.search_across_attachments(
                attachment_ids=attachment_ids,
                query=query,
                limit=self.top_k_chunks,
            )

        # Get attachment info for filenames
        async with get_connection() as conn:
            store = AttachmentStore(conn)
            attachment_map = {}
            for aid in attachment_ids:
                a = await store.get(aid)
                if a:
                    attachment_map[str(aid)] = a.filename

        return [
            {
                "attachment_id": str(chunk.attachment_id),
                "filename": attachment_map.get(str(chunk.attachment_id), "unknown"),
                "chunk_index": chunk.chunk_index,
                "content": chunk.chunk_text,
                "tokens": chunk.token_count or len(chunk.chunk_text) // 4,
                "score": score,
            }
            for chunk, score in results
        ]

    def _is_log_type(self, attachment: Attachment) -> bool:
        """Check if attachment is log/stacktrace type."""
        log_indicators = [
            "log", "error", "trace", "debug",
            "stdout", "stderr", "output",
        ]
        filename_lower = attachment.filename.lower()
        return any(ind in filename_lower for ind in log_indicators)
