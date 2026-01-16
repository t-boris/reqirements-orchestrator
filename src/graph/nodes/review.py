"""Review node - persona-based architectural analysis without Jira operations.

When user asks for review/analysis, this node provides thoughtful architectural
feedback like a senior engineer, without triggering the ticket creation pipeline.

The review is conversational and thorough - a discussion, not a ticket.
"""
import logging
from typing import Any

from src.schemas.state import AgentState
from src.personas import get_persona, get_default_persona, PersonaName

logger = logging.getLogger(__name__)


REVIEW_PROMPT = '''You are {persona_name}, a senior {persona_role}.

{persona_overlay}

Analyze this request thoughtfully, as if thinking out loud:

{context}

User request: {message}

Provide analysis covering:
1. *Understanding* - What you understand about the request
2. *Components & Flows* - Key technical elements involved
3. *Risks & Concerns* - What could go wrong
4. *Alternatives* - Other approaches to consider
5. *Open Questions* - What needs clarification

Be conversational and thorough. This is a discussion, not a ticket.
Think out loud like a senior engineer would.

IMPORTANT: Format for Slack (not Markdown):
- Bold: *text* (single asterisks)
- Italic: _text_ (underscores)
- Code: `code`
- Lists: Use bullet character • or dash -
- NO ### headers (use *Bold Title* instead)
- NO **double asterisks**
'''


def _get_persona_for_review(state: AgentState) -> tuple[str, str, str]:
    """Determine which persona to use for the review.

    Returns:
        Tuple of (persona_name, persona_role, prompt_overlay)

    Persona selection logic:
    1. If intent_result.persona_hint exists -> use that persona
    2. Elif state.persona exists -> use current persona
    3. Else -> default to "architect" (most common for reviews)
    """
    intent_result = state.get("intent_result", {})
    persona_hint = intent_result.get("persona_hint")
    current_persona = state.get("persona")

    # Determine which persona to use
    if persona_hint:
        # Intent classification suggested a specific persona
        persona_name_str = persona_hint
    elif current_persona:
        # Use current persona from state
        persona_name_str = current_persona
    else:
        # Default to architect for reviews
        persona_name_str = "architect"

    # Map string to PersonaName enum
    persona_map = {
        "pm": PersonaName.PM,
        "architect": PersonaName.ARCHITECT,
        "security": PersonaName.SECURITY,
    }
    persona_enum = persona_map.get(persona_name_str, PersonaName.ARCHITECT)

    # Get persona config
    persona_config = get_persona(persona_enum)

    return (
        persona_config.display_name,
        _get_role_for_persona(persona_enum),
        persona_config.prompt_overlay,
    )


def _get_role_for_persona(persona: PersonaName) -> str:
    """Get role description for persona."""
    roles = {
        PersonaName.PM: "Product Manager",
        PersonaName.ARCHITECT: "Technical Architect",
        PersonaName.SECURITY: "Security Analyst",
    }
    return roles.get(persona, "Technical Architect")


def _build_context_string(state: AgentState) -> str:
    """Build context string from conversation context and channel context."""
    parts = []

    # Conversation context (Phase 11)
    conversation_context = state.get("conversation_context")
    if conversation_context:
        summary = conversation_context.get("summary")
        if summary:
            parts.append(f"Conversation background:\n{summary}")

        # Include recent messages if available
        messages = conversation_context.get("messages", [])
        if messages:
            recent = messages[-5:]  # Last 5 messages for context
            msg_texts = []
            for msg in recent:
                user = msg.get("user", "unknown")
                text = msg.get("text", "")[:200]  # Truncate long messages
                msg_texts.append(f"- {user}: {text}")
            if msg_texts:
                parts.append(f"Recent conversation:\n" + "\n".join(msg_texts))

    # Channel context (Phase 8)
    channel_context = state.get("channel_context")
    if channel_context:
        system_context = channel_context.get("system_context")
        if system_context:
            parts.append(f"Project context:\n{system_context}")

    if parts:
        return "\n\n".join(parts)
    return "No additional context available."


async def review_node(state: AgentState) -> dict[str, Any]:
    """Generate persona-based analysis for review requests.

    This node is used for REVIEW intent - when user wants analysis/feedback
    without creating a Jira ticket. It produces thoughtful, conversational
    analysis like a senior engineer would.

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with decision_result containing:
        - action: "review"
        - message: analysis text
        - persona: persona name used
        - topic: topic from intent result (if any)
    """
    from langchain_core.messages import HumanMessage
    from src.llm import get_llm
    from src.schemas.state import ReviewState

    # BEFORE generating new review, check if one already exists
    existing_review = state.get("review_context")
    if existing_review and existing_review.get("state") in [ReviewState.ACTIVE, ReviewState.CONTINUATION]:
        logger.warning(
            "Active review already exists, not overwriting",
            extra={
                "existing_topic": existing_review.get("topic"),
                "existing_state": existing_review.get("state"),
            }
        )
        # Don't overwrite - return decision without updating review_context
        # This prevents Bug #3 (second review overwriting first review's context)
        topic = existing_review.get("topic", "")
        persona = existing_review.get("persona", "Unknown")
        return {
            "decision_result": {
                "action": "review",
                "message": "I notice we already have an active review in progress. Should we continue with that discussion, or would you like to start a new review topic?",
                "persona": persona,
                "topic": topic,
            },
            # Keep existing review_context unchanged
        }

    # Get intent result for persona hint and topic
    intent_result = state.get("intent_result", {})
    topic = intent_result.get("topic")

    # Determine persona
    persona_name, persona_role, persona_overlay = _get_persona_for_review(state)

    # Get latest human message
    messages = state.get("messages", [])
    latest_human_message = ""

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human_message = msg.content
            break

    if not latest_human_message:
        logger.warning("No human message found for review")
        return {
            "decision_result": {
                "action": "review",
                "message": "I don't see a message to review. What would you like me to analyze?",
                "persona": persona_name,
                "topic": topic,
            }
        }

    # Build context string
    context = _build_context_string(state)

    # Build prompt
    prompt = REVIEW_PROMPT.format(
        persona_name=persona_name,
        persona_role=persona_role,
        persona_overlay=persona_overlay,
        context=context,
        message=latest_human_message,
    )

    # Call LLM with higher max_tokens for comprehensive reviews
    llm = get_llm(max_tokens=8192)
    try:
        analysis = await llm.chat(prompt)

        logger.info(
            f"Review node generated analysis: {len(analysis)} chars",
            extra={
                "persona": persona_name,
                "topic": topic,
                "state": ReviewState.ACTIVE,
                "message_length": len(latest_human_message),
                "analysis_length": len(analysis),
            },
        )

        # Build review_context for architecture decision tracking (Phase 14)
        # This enables DECISION_APPROVAL detection on subsequent messages
        from datetime import datetime, timezone
        import time

        review_context = {
            "state": ReviewState.ACTIVE,  # SET STATE - review just posted, awaiting user response
            "topic": topic or latest_human_message[:100],  # Use message start if no topic
            "review_summary": analysis,
            "persona": persona_name,
            "review_timestamp": datetime.now(timezone.utc).isoformat(),
            "thread_ts": state.get("thread_ts", ""),
            "channel_id": state.get("channel_id", ""),
            "created_at": time.time(),
        }

        return {
            "decision_result": {
                "action": "review",
                "message": analysis,
                "persona": persona_name,
                "topic": topic,
            },
            "review_context": review_context,
        }

    except Exception as e:
        logger.error(f"Review node LLM call failed: {e}")
        return {
            "decision_result": {
                "action": "review",
                "message": f"I encountered an error while generating the analysis: {str(e)}",
                "persona": persona_name,
                "topic": topic,
            }
        }


# Patterns that indicate user is done with review (triggers freeze)
REVIEW_COMPLETE_PATTERNS = [
    r"\bthanks?\b",
    r"\bok\b",
    r"\bgot it\b",
    r"\ball good\b",
    r"\blooks?\s+good\b",
    r"\bperfect\b",
    r"\bgreat\b",
]


def freeze_review(state: dict) -> dict:
    """Freeze current review context into artifact.

    Called when REVIEW_COMPLETE detected (thanks/ok/got it).
    Moves review_context -> review_artifact and clears review_context.

    Freeze semantics (from 20-CONTEXT.md):
    - review_artifact remains accessible for Review→Ticket handoff
    - But doesn't trigger continuation automatically
    - And doesn't bias next message's intent classification

    Returns:
        State update with review_artifact set and review_context cleared
    """
    from src.schemas.state import ReviewArtifact

    review_context = state.get("review_context")
    if not review_context:
        return {}

    from datetime import datetime, timezone

    # Map persona name to ReviewArtifact kind
    persona = review_context.get("persona", "architect")
    persona_to_kind = {
        "Architect": "architecture",
        "Security Analyst": "security",
        "Product Manager": "pm",
        # Fallback mappings for lowercase
        "architect": "architecture",
        "security": "security",
        "pm": "pm",
    }
    kind = persona_to_kind.get(persona, "architecture")

    artifact: ReviewArtifact = {
        "summary": review_context.get("review_summary", ""),
        "kind": kind,
        "version": 1,  # First freeze is v1
        "topic": review_context.get("topic", ""),
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "thread_ts": review_context.get("thread_ts", ""),
    }

    logger.info(
        "Freezing review context into artifact",
        extra={
            "topic": artifact["topic"],
            "kind": artifact["kind"],
            "thread_ts": artifact["thread_ts"],
        },
    )

    return {
        "review_artifact": artifact,
        "review_context": None,  # Clear to stop continuation triggers
    }


# Full synthesis prompt - combines all patches into complete document
FULL_SYNTHESIS_PROMPT = '''Generate a complete architecture synthesis incorporating all previous patches.

Original topic: {topic}
Persona: {persona}

Previous review versions:
{all_patches}

Current state of open questions:
{open_questions}

Generate a COMPLETE architecture document that:
1. Incorporates all decisions from all versions
2. Reflects current risks and mitigations
3. Lists any remaining open questions
4. Provides clear recommendations

This is the full synthesis - be comprehensive but structured.

Format for Slack (not Markdown):
- Bold: *text* (single asterisks)
- Italic: _text_ (underscores)
- Code: `code`
- Lists: Use bullet character • or dash -
- NO ### headers (use *Bold Title:* instead)
- NO **double asterisks**
'''


async def generate_full_synthesis(state: dict) -> dict:
    """Generate full architecture synthesis from all patches.

    Triggered by "Show full architecture" button.
    Combines all patch history into complete document.

    Args:
        state: Current AgentState dict

    Returns:
        State update with decision_result containing full synthesis
    """
    from src.llm import get_llm

    review_context = state.get("review_context", {})
    review_artifact = state.get("review_artifact", {})

    # Gather all patches/versions from review history
    patches = []

    # Include frozen artifact if exists
    if review_artifact:
        version = review_artifact.get("version", 1)
        summary = review_artifact.get("summary", "")
        if summary:
            patches.append(f"v{version} (archived): {summary}")

    # Include current review context
    if review_context:
        version = review_context.get("version", 1)
        summary = review_context.get("review_summary", "")
        updated = review_context.get("updated_recommendation", "")

        if summary:
            patches.append(f"v{version} (original): {summary}")
        if updated:
            patches.append(f"v{version} (updated): {updated}")

    # Get topic and persona
    topic = (
        review_context.get("topic") or
        review_artifact.get("topic", "architecture")
    )
    persona = (
        review_context.get("persona") or
        review_artifact.get("kind", "architect")
    )

    # Build open questions section
    open_questions = "See previous patches for open questions"
    if review_context.get("updated_recommendation"):
        # Try to extract open questions from latest patch
        open_questions = "Review latest patch for current open questions"

    llm = get_llm()
    prompt = FULL_SYNTHESIS_PROMPT.format(
        topic=topic,
        persona=persona,
        all_patches="\n\n---\n\n".join(patches) if patches else "No previous patches",
        open_questions=open_questions,
    )

    try:
        full_review = await llm.chat(prompt)

        logger.info(
            "Full synthesis generated",
            extra={
                "topic": topic,
                "persona": persona,
                "patch_count": len(patches),
                "synthesis_length": len(full_review),
            },
        )

        return {
            "decision_result": {
                "action": "full_synthesis",
                "review": full_review,
                "message": full_review,
                "topic": topic,
                "persona": persona,
                "is_full_synthesis": True,
            },
        }

    except Exception as e:
        logger.error(f"Full synthesis LLM call failed: {e}")
        return {
            "decision_result": {
                "action": "full_synthesis",
                "message": f"I encountered an error generating the full synthesis: {str(e)}",
                "topic": topic,
                "persona": persona,
            }
        }
