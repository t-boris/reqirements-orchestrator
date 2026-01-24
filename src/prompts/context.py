"""Prompt templates for attachment context injection.

Formats AttachmentContext for LLM consumption.
Includes pinned content, retrieved chunks, and source citations.

Key rule: Never include whole file - only chunks (300-800 tokens), top 3-6 per retrieval.
"""
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.documents.retriever import AttachmentContext


def format_attachment_context(
    context: Optional["AttachmentContext"],
    mode: str = "default",
) -> str:
    """Format attachment context for prompt injection.

    Args:
        context: AttachmentContext from retriever.
        mode: Formatting mode (default, structured, cited).

    Returns:
        Formatted prompt section or empty string.
    """
    if not context:
        return ""

    if not context.pinned and not context.retrieved_chunks:
        return ""

    parts = []

    # Header
    parts.append("## Document Context")
    parts.append("")

    # Pinned attachments (full inclusion)
    if context.pinned:
        parts.append("### Pinned Documents")
        parts.append("The following documents have been explicitly pinned to this context:")
        parts.append("")

        for p in context.pinned:
            parts.append(f"#### {p['filename']}")
            parts.append(p.get("content", ""))
            parts.append("")

    # Retrieved chunks (relevance-based)
    if context.retrieved_chunks:
        parts.append("### Relevant Document Sections")
        parts.append("The following sections were retrieved based on relevance to your query:")
        parts.append("")

        for i, chunk in enumerate(context.retrieved_chunks, 1):
            source_ref = f"[{chunk['filename']}:{chunk['chunk_index']}]"
            parts.append(f"**Section {i}** {source_ref}")
            parts.append("```")
            parts.append(chunk["content"])
            parts.append("```")
            parts.append("")

    # Citation instructions for DECIDE mode
    if mode == "cited":
        parts.append("### Citation Requirements")
        parts.append("When referencing information from these documents, cite using format: [filename:section]")
        parts.append("")

    return "\n".join(parts)


def format_attachment_summary(
    context: Optional["AttachmentContext"],
) -> str:
    """Format brief attachment summary for status display.

    Args:
        context: AttachmentContext from retriever.

    Returns:
        One-line summary like "Using: spec.pdf (3 sections), api.md (pinned)"
    """
    if not context:
        return ""

    if not context.pinned and not context.retrieved_chunks:
        return ""

    # Count by file
    file_counts: dict[str, str | int] = {}
    for p in context.pinned:
        file_counts[p["filename"]] = "pinned"

    for c in context.retrieved_chunks:
        filename = c["filename"]
        if filename not in file_counts:
            file_counts[filename] = 0
        if isinstance(file_counts[filename], int):
            file_counts[filename] += 1

    # Format
    parts = []
    for filename, count in file_counts.items():
        if count == "pinned":
            parts.append(f"{filename} (pinned)")
        else:
            parts.append(f"{filename} ({count} sections)")

    return "Using: " + ", ".join(parts)


def build_rag_system_prompt(
    base_prompt: str,
    attachment_context: Optional["AttachmentContext"],
    mode: str = "default",
) -> str:
    """Build system prompt with RAG context injection.

    Args:
        base_prompt: Original system prompt.
        attachment_context: Resolved attachment context.
        mode: Formatting mode.

    Returns:
        Combined system prompt with document context.
    """
    if not attachment_context:
        return base_prompt

    doc_section = format_attachment_context(attachment_context, mode=mode)
    if not doc_section:
        return base_prompt

    # Inject document context after system instructions, before user content
    return f"{base_prompt}\n\n{doc_section}"
