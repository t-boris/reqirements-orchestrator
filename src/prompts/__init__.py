"""Prompt templates for LLM interactions.

This module provides prompt formatting functions for:
- Attachment context injection (RAG)
- System prompt building
"""

from src.prompts.context import (
    build_rag_system_prompt,
    format_attachment_context,
    format_attachment_summary,
)

__all__ = [
    "build_rag_system_prompt",
    "format_attachment_context",
    "format_attachment_summary",
]
