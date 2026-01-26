"""Draft field extraction - prompts and helpers for extracting ticket fields.

Contains:
- Extraction prompts for standard and reference-aware extraction
- Channel context formatting
- Content generation for fields
- Reference detection helpers
"""
import json
import logging
import re
from typing import Any, Optional

from src.schemas.draft import TicketDraft
from src.llm import get_llm

logger = logging.getLogger(__name__)


def format_channel_context(channel_context: Optional[dict]) -> str:
    """Format channel context (decisions, artifacts) for injection into prompt.

    Args:
        channel_context: Channel context dict with recent_artifacts, recent_decisions, active_epics, etc.

    Returns:
        Formatted string for prompt injection, or empty string if no context.
    """
    if not channel_context:
        return ""

    parts = []

    # Active epics
    active_epics = channel_context.get("active_epics", [])
    if active_epics:
        epics_str = ", ".join(active_epics[:5])
        parts.append(f"Active epics: {epics_str}")

    # Recent decisions from DecisionStore (Phase 39)
    recent_decisions = channel_context.get("recent_decisions", [])
    if recent_decisions:
        parts.append("*Architecture Decisions:*")
        for d in recent_decisions[:10]:  # Top 10 decisions
            title = d.get("title", "Untitled")
            description = d.get("description", "")
            parts.append(f"  - {title}")
            if description:
                parts.append(f"    {description[:150]}")

    # Recent artifacts with decisions
    recent_artifacts = channel_context.get("recent_artifacts", [])
    if recent_artifacts:
        for artifact in recent_artifacts[:3]:  # Top 3 artifacts
            kind = artifact.get("kind", "")
            summary = artifact.get("summary", "")
            decisions = artifact.get("decisions", [])

            if decisions:
                artifact_header = f"Recent {kind} review"
                if summary:
                    artifact_header += f": {summary[:100]}"
                parts.append(artifact_header)

                for i, decision in enumerate(decisions, 1):
                    parts.append(f"  Decision {i}: {decision}")

    if not parts:
        return ""

    return "\nChannel context (stored decisions and artifacts):\n" + "\n".join(parts) + "\n"


def detect_reference_to_prior_content(message: str) -> bool:
    """Check if user message references prior content in thread.

    Returns True if message contains patterns like:
    - "the architecture" / "this architecture"
    - "the review" / "this review" / "that analysis"
    - "from above" / "mentioned above"
    """
    message_lower = message.lower()

    reference_patterns = [
        r"\bthe\s+(?:architecture|review|analysis|design|proposal|approach)\b",
        r"\bthis\s+(?:architecture|review|analysis|design|proposal|approach)\b",
        r"\bthat\s+(?:architecture|review|analysis|design|proposal|approach)\b",
        r"\b(?:from|mentioned|discussed)\s+above\b",
        r"\bour\s+(?:discussion|conversation|review)\b",
    ]

    for pattern in reference_patterns:
        if re.search(pattern, message_lower):
            return True
    return False


# =============================================================================
# Extraction Prompts
# =============================================================================

EXTRACTION_PROMPT = '''You are extracting requirements from a conversation to build a Jira ticket draft.
{channel_context}
Current draft state:
{draft_json}
{conversation_context}
New message to process:
{message}

Extract any new information that should update the draft. Consider BOTH the conversation context above AND the new message. Return a JSON object with ONLY the fields that have new information. Do not repeat existing values.

Fields you can update:
- title: Clear, concise ticket title (do NOT prefix with "Epic:", "Story:", etc.)
- problem: What problem we're solving
- proposed_solution: How we'll solve it
- acceptance_criteria: List of testable criteria (append new ones)
- constraints: List of {{"key", "value"}} technical decisions
- dependencies: List of external dependencies
- risks: List of potential risks
- issue_type: Type of work item (epic, story, task, bug)
  Only set if user explicitly mentions type: "create an epic", "make a story", "this is a bug"
- requested_scope: What to generate (epics_only, full_plan, single_item)
  - epics_only: User says "only epic(s)", "just epics", "epic-level only"
  - full_plan: User says "full breakdown", "complete plan", "with stories"
  - single_item: Default for normal requests

Return empty object {{}} if no new information to extract.

IMPORTANT: Only extract factual information stated in the message. Do not invent or assume.
IMPORTANT: Do NOT put "Epic:" or "Story:" prefixes in the title. Use issue_type field instead.

JSON response:'''


EXTRACTION_PROMPT_WITH_REFERENCE = '''You are extracting requirements from a conversation to build a Jira ticket draft.

The user is referencing prior discussion in the thread. Here is the recent context:

{thread_context}
{review_artifact_context}
---
{channel_context}
Current draft state:
{draft_json}

New message to process:
{message}

Extract information from the user's request, using the thread context and architecture review as reference material.
If the user says "create tickets for the architecture" or similar, extract multiple tickets from
the architecture review sections (components, risks, flows, etc.).

Fields you can update:
- title: Clear, concise ticket title (do NOT prefix with "Epic:", "Story:", etc.)
- problem: What problem we're solving
- proposed_solution: How we'll solve it
- acceptance_criteria: List of testable criteria (append new ones)
- constraints: List of {{"key", "value"}} technical decisions
- dependencies: List of external dependencies
- risks: List of potential risks
- issue_type: Type of work item (epic, story, task, bug)
  Only set if user explicitly mentions type: "create an epic", "make a story", "this is a bug"
- requested_scope: What to generate (epics_only, full_plan, single_item)
  - epics_only: User says "only epic(s)", "just epics", "epic-level only"
  - full_plan: User says "full breakdown", "complete plan", "with stories"
  - single_item: Default for normal requests

Return empty object {{}} if no new information to extract.

IMPORTANT: Only extract factual information stated in the message, thread context, or architecture review. Do not invent or assume.
IMPORTANT: Do NOT put "Epic:" or "Story:" prefixes in the title. Use issue_type field instead.

JSON response:'''


GENERATION_PROMPT = '''You are helping build a Jira ticket. The user has asked you to propose content for specific fields.

Current draft:
{draft_json}

Context from the conversation:
{context}

Please generate content for these fields:
{fields_to_generate}

Return a JSON object with the generated content. For acceptance_criteria, provide a list of 3-5 testable criteria. For other fields, provide appropriate content based on the context.

JSON response:'''


async def generate_content_for_fields(draft: TicketDraft, fields: list[str], state: dict) -> None:
    """Generate content for fields when user asks us to propose.

    Modifies draft in-place with generated content.
    """
    if not fields:
        return

    llm = get_llm()
    draft_json = draft.model_dump_json(exclude={"evidence_links", "created_at", "updated_at"})

    # Build context from conversation and draft
    context_parts = []
    if draft.title:
        context_parts.append(f"Title: {draft.title}")
    if draft.problem:
        context_parts.append(f"Problem: {draft.problem}")
    if draft.proposed_solution:
        context_parts.append(f"Proposed solution: {draft.proposed_solution}")

    conversation_context = state.get("conversation_context", {})
    if conversation_context.get("summary"):
        context_parts.append(f"Conversation: {conversation_context['summary']}")

    context = "\n".join(context_parts) if context_parts else "No additional context"

    prompt = GENERATION_PROMPT.format(
        draft_json=draft_json,
        context=context,
        fields_to_generate="\n".join(f"- {f}" for f in fields),
    )

    try:
        response_text = await llm.chat(prompt)
        response_text = response_text.strip()

        # Parse JSON response
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        generated = json.loads(response_text) if response_text else {}

        # Handle case where LLM returns a list (multi-ticket request)
        if isinstance(generated, list):
            if generated:
                logger.info(f"LLM returned list of {len(generated)} items, using first item")
                generated = generated[0] if isinstance(generated[0], dict) else {}
            else:
                generated = {}

        if generated:
            logger.info(f"Generated content for fields: {list(generated.keys())}")
            # Patch draft with generated content
            for field, value in generated.items():
                # Skip constraints - they require special DraftConstraint format
                # that the LLM won't generate correctly
                if field == "constraints":
                    logger.debug("Skipping generated constraints - requires structured format")
                    continue
                # Skip open_questions - not a draft field
                if field == "open_questions":
                    logger.debug("Skipping open_questions - not a draft field")
                    continue
                if hasattr(draft, field):
                    if isinstance(value, list) and field in ["acceptance_criteria", "dependencies", "risks"]:
                        # Append to lists
                        existing = getattr(draft, field, [])
                        setattr(draft, field, existing + value)
                    else:
                        setattr(draft, field, value)

    except Exception as e:
        logger.warning(f"Failed to generate content: {e}")
