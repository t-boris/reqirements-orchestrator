"""Provider-specific prompt overlays.

Different LLMs respond better to different instruction styles.
Overlays modify base prompts for optimal behavior per provider.
"""

from src.llm.types import LLMProvider

# Provider-specific system prompt additions
SYSTEM_OVERLAYS: dict[LLMProvider, str] = {
    LLMProvider.GEMINI: """
When extracting JSON, be precise with field names and types.
Use the exact field names from the schema.""",

    LLMProvider.OPENAI: """
Follow the JSON schema exactly. Do not add extra fields.
When uncertain, ask for clarification rather than guessing.""",

    LLMProvider.ANTHROPIC: """
Think step by step when extracting information.
Explain your reasoning briefly before providing the JSON output.""",
}

# Provider-specific extraction hints
EXTRACTION_OVERLAYS: dict[LLMProvider, str] = {
    LLMProvider.GEMINI: """
Output format: Return ONLY valid JSON, no markdown code blocks.""",

    LLMProvider.OPENAI: """
Output format: Return valid JSON wrapped in ```json``` code block.""",

    LLMProvider.ANTHROPIC: """
First briefly note what you extracted, then return the JSON in a code block.""",
}

def get_system_overlay(provider: LLMProvider) -> str:
    """Get system prompt overlay for provider."""
    return SYSTEM_OVERLAYS.get(provider, "")

def get_extraction_overlay(provider: LLMProvider) -> str:
    """Get extraction prompt overlay for provider."""
    return EXTRACTION_OVERLAYS.get(provider, "")

def apply_overlay(base_prompt: str, overlay: str) -> str:
    """Apply overlay to base prompt."""
    if not overlay:
        return base_prompt
    return f"{base_prompt}\n\n{overlay.strip()}"
