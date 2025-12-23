"""
Persona Loader - Load and manage specialized agent personas.

Personas are specialized agents with:
- Custom knowledge bases (markdown files)
- Personality parameters (humor, emoji, formality)
- Dedicated LLM models
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

from src.config.settings import get_settings

logger = structlog.get_logger()
settings = get_settings()


# =============================================================================
# Persona Data Classes
# =============================================================================


@dataclass
class PersonaConfig:
    """Configuration for a persona."""

    name: str
    display_name: str
    description: str
    system_prompt: str
    knowledge_base: str  # Combined content from markdown files
    model: str  # LLM model to use
    personality: "PersonalityConfig" = field(default_factory=lambda: PersonalityConfig())
    triggers: list[str] = field(default_factory=list)  # Keywords that activate this persona


@dataclass
class PersonalityConfig:
    """Personality parameters for a persona."""

    humor: float = 0.0  # 0-1: how humorous
    emoji_usage: float = 0.0  # 0-1: how much to use emojis
    formality: float = 0.5  # 0-1: formal (1) vs casual (0)
    verbosity: float = 0.5  # 0-1: verbose (1) vs concise (0)


# =============================================================================
# Persona Registry
# =============================================================================

# Default persona configurations
DEFAULT_PERSONAS: dict[str, dict[str, Any]] = {
    "architect": {
        "display_name": "Solution Architect",
        "description": "Technical architecture, system design, and component structure",
        "triggers": [
            "architecture",
            "system design",
            "component",
            "microservice",
            "integration",
            "api design",
            "database design",
            "scalability",
            "performance",
        ],
        "personality": {
            "humor": 0.1,
            "emoji_usage": 0.1,
            "formality": 0.8,
            "verbosity": 0.6,
        },
        "model": "gpt-4o",
    },
    "product_manager": {
        "display_name": "Product Manager",
        "description": "User stories, acceptance criteria, business value, and prioritization",
        "triggers": [
            "user story",
            "acceptance criteria",
            "business value",
            "priority",
            "mvp",
            "roadmap",
            "stakeholder",
            "requirement",
            "feature",
        ],
        "personality": {
            "humor": 0.2,
            "emoji_usage": 0.3,
            "formality": 0.6,
            "verbosity": 0.5,
        },
        "model": "gpt-4o",
    },
    "security_analyst": {
        "display_name": "Security Analyst",
        "description": "Security requirements, compliance, vulnerabilities, and risk assessment",
        "triggers": [
            "security",
            "authentication",
            "authorization",
            "compliance",
            "gdpr",
            "vulnerability",
            "encryption",
            "audit",
            "risk",
        ],
        "personality": {
            "humor": 0.0,
            "emoji_usage": 0.0,
            "formality": 0.9,
            "verbosity": 0.7,
        },
        "model": "gpt-4o",
    },
}


# Loaded personas cache
_personas: dict[str, PersonaConfig] = {}


# =============================================================================
# Loader Functions
# =============================================================================


def get_personas_dir() -> Path:
    """Get the personas directory path."""
    # Look for personas/ in project root
    current = Path.cwd()
    personas_dir = current / "personas"

    if not personas_dir.exists():
        # Try relative to src
        personas_dir = current.parent / "personas"

    return personas_dir


async def load_personas() -> dict[str, PersonaConfig]:
    """
    Load all personas from configuration and knowledge base files.

    Returns:
        Dictionary of persona name to PersonaConfig.
    """
    global _personas

    if _personas:
        return _personas

    personas_dir = get_personas_dir()
    logger.info("loading_personas", personas_dir=str(personas_dir))

    for name, config in DEFAULT_PERSONAS.items():
        persona_dir = personas_dir / name

        # Load knowledge base from markdown files
        knowledge_base = ""
        if persona_dir.exists():
            knowledge_base = _load_knowledge_base(persona_dir)

        # Build system prompt
        system_prompt = _build_system_prompt(name, config, knowledge_base)

        # Create persona config
        _personas[name] = PersonaConfig(
            name=name,
            display_name=config["display_name"],
            description=config["description"],
            system_prompt=system_prompt,
            knowledge_base=knowledge_base,
            model=config.get("model", settings.default_llm_model),
            personality=PersonalityConfig(**config.get("personality", {})),
            triggers=config.get("triggers", []),
        )

        logger.info(
            "persona_loaded",
            name=name,
            knowledge_size=len(knowledge_base),
        )

    return _personas


def _load_knowledge_base(persona_dir: Path) -> str:
    """
    Load and combine all markdown files in a persona directory.

    Args:
        persona_dir: Path to persona directory.

    Returns:
        Combined content of all markdown files.
    """
    content_parts = []

    for md_file in sorted(persona_dir.glob("*.md")):
        try:
            with open(md_file, "r", encoding="utf-8") as f:
                content = f.read()
                # Add file name as section header
                content_parts.append(f"# {md_file.stem}\n\n{content}")
        except Exception as e:
            logger.warning("failed_to_load_knowledge", file=str(md_file), error=str(e))

    return "\n\n---\n\n".join(content_parts)


def _build_system_prompt(name: str, config: dict, knowledge_base: str) -> str:
    """
    Build the system prompt for a persona.

    Args:
        name: Persona name.
        config: Persona configuration.
        knowledge_base: Loaded knowledge base content.

    Returns:
        Complete system prompt.
    """
    personality = config.get("personality", {})
    formality = personality.get("formality", 0.5)
    verbosity = personality.get("verbosity", 0.5)

    # Build personality instructions
    personality_instructions = []

    if formality > 0.7:
        personality_instructions.append("Use formal, professional language.")
    elif formality < 0.3:
        personality_instructions.append("Use casual, friendly language.")

    if verbosity > 0.7:
        personality_instructions.append("Provide detailed, thorough explanations.")
    elif verbosity < 0.3:
        personality_instructions.append("Be concise and to the point.")

    if personality.get("humor", 0) > 0.5:
        personality_instructions.append("Include occasional appropriate humor.")

    if personality.get("emoji_usage", 0) > 0.3:
        personality_instructions.append("Use emojis sparingly to enhance communication.")

    prompt_parts = [
        f"You are a {config['display_name']} helping with requirements engineering.",
        f"\n{config['description']}",
        "\n\n## Your Expertise",
        f"Your areas of focus: {', '.join(config.get('triggers', []))}",
    ]

    if personality_instructions:
        prompt_parts.append("\n\n## Communication Style")
        prompt_parts.extend(personality_instructions)

    if knowledge_base:
        prompt_parts.append("\n\n## Knowledge Base")
        prompt_parts.append("Use the following knowledge to inform your responses:")
        prompt_parts.append(f"\n{knowledge_base}")

    prompt_parts.append("\n\n## Guidelines")
    prompt_parts.append("- Focus on your area of expertise")
    prompt_parts.append("- Provide actionable recommendations")
    prompt_parts.append("- Ask clarifying questions when needed")
    prompt_parts.append("- Reference your knowledge base when relevant")

    return "\n".join(prompt_parts)


# =============================================================================
# Persona Access Functions
# =============================================================================


async def get_persona(name: str) -> PersonaConfig | None:
    """
    Get a persona by name.

    Args:
        name: Persona name.

    Returns:
        PersonaConfig or None if not found.
    """
    personas = await load_personas()
    return personas.get(name)


async def get_all_personas() -> list[PersonaConfig]:
    """
    Get all loaded personas.

    Returns:
        List of PersonaConfig objects.
    """
    personas = await load_personas()
    return list(personas.values())


async def get_persona_for_triggers(keywords: list[str]) -> PersonaConfig | None:
    """
    Find the best matching persona for given keywords.

    Args:
        keywords: List of keywords from the message.

    Returns:
        Best matching PersonaConfig or None.
    """
    personas = await load_personas()
    keywords_lower = {k.lower() for k in keywords}

    best_match = None
    best_score = 0

    for persona in personas.values():
        # Count trigger matches
        matches = sum(
            1 for trigger in persona.triggers if trigger.lower() in keywords_lower
        )

        if matches > best_score:
            best_score = matches
            best_match = persona

    if best_match and best_score > 0:
        logger.debug(
            "persona_matched",
            persona=best_match.name,
            score=best_score,
        )

    return best_match


# =============================================================================
# LLM Integration
# =============================================================================


async def get_persona_llm(persona_name: str):
    """
    Get an LLM instance configured for a persona.

    Args:
        persona_name: Name of the persona.

    Returns:
        Configured LLM instance.
    """
    from langchain_openai import ChatOpenAI

    persona = await get_persona(persona_name)
    if not persona:
        # Return default LLM
        return ChatOpenAI(model=settings.default_llm_model)

    return ChatOpenAI(
        model=persona.model,
        temperature=0.4,  # Slightly creative for personas
    )


async def invoke_persona(
    persona_name: str,
    message: str,
    context: str = "",
) -> str:
    """
    Invoke a persona to generate a response.

    Args:
        persona_name: Name of the persona.
        message: User message.
        context: Additional context.

    Returns:
        Persona's response.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    persona = await get_persona(persona_name)
    if not persona:
        return "Persona not found."

    llm = await get_persona_llm(persona_name)

    messages = [
        SystemMessage(content=persona.system_prompt),
    ]

    if context:
        messages.append(SystemMessage(content=f"Context: {context}"))

    messages.append(HumanMessage(content=message))

    response = await llm.ainvoke(messages)
    return response.content
