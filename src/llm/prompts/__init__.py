"""Prompt management system with base templates and provider-specific overlays.

Usage:
    from src.llm.prompts import PromptBuilder, get_prompt_builder, LLMProvider

    builder = get_prompt_builder(LLMProvider.GEMINI)
    messages = builder.build_extraction_prompt(
        ticket_type="Story",
        draft={"summary": "..."},
        missing_fields=["acceptance_criteria"],
        conversation="User said...",
    )
"""

from src.llm.prompts.templates import (
    ANALYST_SYSTEM_BASE,
    EXTRACTION_TEMPLATE,
    VALIDATION_TEMPLATE,
    QUESTIONING_TEMPLATE,
    PREVIEW_TEMPLATE,
)
from src.llm.prompts.builder import (
    PromptBuilder,
    get_prompt_builder,
)
from src.llm.prompts.overlays import (
    get_system_overlay,
    get_extraction_overlay,
)

__all__ = [
    # Templates
    "ANALYST_SYSTEM_BASE",
    "EXTRACTION_TEMPLATE",
    "VALIDATION_TEMPLATE",
    "QUESTIONING_TEMPLATE",
    "PREVIEW_TEMPLATE",
    # Builder
    "PromptBuilder",
    "get_prompt_builder",
    # Overlays
    "get_system_overlay",
    "get_extraction_overlay",
]
