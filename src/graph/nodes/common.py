"""
LangGraph Nodes - All node functions for the requirements workflow.

Each node is a pure function that takes state and returns state updates.
Nodes are composed into the graph in graph.py.
"""

import json
from pathlib import Path
import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.language_models import BaseChatModel

from src.config.settings import get_settings

# Persona knowledge cache
_persona_knowledge_cache: dict[str, str] = {}
from src.graph.state import (
    HumanDecision,
    IntentType,
    RequirementState,
    WorkflowPhase,
    ProgressStepStatus,
)
# Note: get_model_provider imported lazily inside get_llm() to avoid circular import

logger = structlog.get_logger()
settings = get_settings()


# =============================================================================
# Helper Functions
# =============================================================================

def parse_llm_json_response(response) -> dict:
    """
    Parse JSON from LLM response, handling various content formats.

    Args:
        response: LLM response object with .content attribute.

    Returns:
        Parsed JSON as dict.

    Raises:
        json.JSONDecodeError: If JSON parsing fails.
    """
    content = response.content

    # Handle list content format (Google Gemini)
    if isinstance(content, list):
        content = "".join(
            part.get("text", str(part)) if isinstance(part, dict) else str(part)
            for part in content
        )

    # Extract JSON from markdown code blocks
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]

    return json.loads(content.strip())


# =============================================================================
# Response Target Decision
# =============================================================================

def determine_response_target(
    state: RequirementState,
    new_phase: str | None = None,
    is_final_summary: bool = False,
    is_clarifying: bool = False,
) -> str:
    """
    Determine where to send the response: thread, channel, or broadcast.

    Logic:
    - Phase transition (entering new major phase) → "channel" (new thread)
    - Final review/summary → "broadcast" (visible in channel)
    - Clarifying questions within same phase → "thread"
    - General Q&A, simple responses → "thread"

    Args:
        state: Current graph state.
        new_phase: If entering a new phase, the phase name.
        is_final_summary: True if this is the final workflow summary.
        is_clarifying: True if asking clarifying questions.

    Returns:
        "thread" | "channel" | "broadcast"
    """
    # Final summary always goes to channel with broadcast
    if is_final_summary:
        return "broadcast"

    # Clarifying questions stay in thread
    if is_clarifying:
        return "thread"

    # Check for phase transition
    current_phase = state.get("current_phase")
    phase_history = state.get("phase_history", [])

    # Major phases that warrant a new channel message
    major_phases = {
        "architecture",  # Presenting architecture options
        "scope",         # Defining scope/epics
        "stories",       # Breaking down stories
        "review",        # Final review
        "jira_sync",     # Syncing to Jira
    }

    # If entering a new major phase that wasn't visited before
    if new_phase and new_phase in major_phases:
        if new_phase not in phase_history:
            return "channel"

    # If current response is about a phase transition
    if current_phase in major_phases and current_phase not in phase_history:
        return "channel"

    # Default: respond in thread
    return "thread"


# =============================================================================
# LLM Factory
# =============================================================================

def get_llm_for_state(state: RequirementState, temperature: float = 0.3) -> BaseChatModel:
    """
    Get the appropriate LLM based on channel configuration.

    Uses channel_config to determine which model and provider to use.
    Falls back to default settings if no config.

    Args:
        state: Current graph state with channel_config.
        temperature: LLM temperature setting.

    Returns:
        Configured LLM instance.
    """
    # Lazy import to avoid circular dependency
    from src.slack.channel_config_store import get_model_provider

    config = state.get("channel_config", {})
    model_name = config.get("default_model", settings.default_llm_model)
    provider = get_model_provider(model_name)

    print(f"[DEBUG] get_llm_for_state: model={model_name}, provider={provider}")

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model_name, temperature=temperature)
    elif provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
    else:  # Default to OpenAI
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name, temperature=temperature)


def get_personality_prompt(state: RequirementState) -> str:
    """
    Generate personality instructions based on channel config.

    Args:
        state: Current graph state with channel_config.

    Returns:
        Personality instruction string to append to prompts.
    """
    config = state.get("channel_config", {})
    personality = config.get("personality", {})

    if not personality:
        return ""

    humor = personality.get("humor", 0.2)
    formality = personality.get("formality", 0.6)
    emoji = personality.get("emoji_usage", 0.2)
    verbosity = personality.get("verbosity", 0.5)

    instructions = []

    # Humor
    if humor < 0.3:
        instructions.append("Be professional and serious.")
    elif humor > 0.7:
        instructions.append("Feel free to use appropriate humor and wit.")

    # Formality
    if formality < 0.3:
        instructions.append("Use a casual, friendly tone.")
    elif formality > 0.7:
        instructions.append("Use formal, professional language.")

    # Emoji
    if emoji < 0.3:
        instructions.append("Avoid using emojis.")
    elif emoji > 0.7:
        instructions.append("Use emojis where appropriate to be expressive.")

    # Verbosity
    if verbosity < 0.3:
        instructions.append("Be very concise and brief.")
    elif verbosity > 0.7:
        instructions.append("Provide detailed, thorough explanations.")

    if instructions:
        return "\n\nCommunication style: " + " ".join(instructions)
    return ""


def get_persona_knowledge(persona_name: str | None, state: RequirementState) -> str:
    """
    Load ALL files from persona directory and channel config.

    Combines:
    1. All files from personas/{name}/ directory (*.md, *.txt, *.yaml, etc.)
    2. Channel-specific overrides from channel_config.persona_knowledge

    Args:
        persona_name: Name of the persona (architect, product_manager, security_analyst)
        state: Current graph state with channel_config.

    Returns:
        Combined persona knowledge string.
    """
    if not persona_name:
        return ""

    global _persona_knowledge_cache

    # Load ALL files from persona directory if not cached
    if persona_name not in _persona_knowledge_cache:
        persona_dir = Path(__file__).parent.parent.parent / "personas" / persona_name
        knowledge_parts = []

        if persona_dir.exists() and persona_dir.is_dir():
            # Load all text-based files from the directory
            supported_extensions = {".md", ".txt", ".yaml", ".yml", ".json"}
            for file_path in sorted(persona_dir.iterdir()):
                if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                    try:
                        content = file_path.read_text()
                        knowledge_parts.append(f"### {file_path.name}\n{content}")
                    except Exception as e:
                        logger.warning("persona_file_read_failed", file=str(file_path), error=str(e))

        _persona_knowledge_cache[persona_name] = "\n\n".join(knowledge_parts)

    base_knowledge = _persona_knowledge_cache.get(persona_name, "")

    # Get channel-specific overrides
    config = state.get("channel_config", {})
    persona_overrides = config.get("persona_knowledge", {}).get(persona_name, {})
    inline_knowledge = persona_overrides.get("inline", "")

    # Combine knowledge
    parts = []
    if base_knowledge:
        parts.append(f"=== {persona_name.replace('_', ' ').title()} Persona ===\n{base_knowledge}")
    if inline_knowledge:
        parts.append(f"\n=== Channel-Specific Context ===\n{inline_knowledge}")

    return "\n".join(parts)

