"""Response generation nodes."""

import structlog
from langchain_core.prompts import ChatPromptTemplate

from src.graph.state import (
    HumanDecision,
    IntentType,
    RequirementState,
    WorkflowPhase,
)

from src.graph.nodes.common import (
    get_llm_for_state,
    get_persona_knowledge,
    logger,
)

# =============================================================================
# Response Generation Node
# =============================================================================

RESPONSE_PROMPT = """You are a requirements engineering assistant responding to a user.
{persona_knowledge}

## User's Message
{user_message}

## Current Context
- Intent: {intent}
- Active Persona: {active_persona}
- Draft requirement: {draft}
- All drafts (if complex): {all_drafts}
- Conflicts detected: {conflicts}
- Jira Issue created: {jira_key}
- Error (if any): {error}

## Response Guidelines by Intent

**If intent is "question":**
- DIRECTLY answer the user's question using your expertise
- If asking about a draft/requirement, provide specific feedback
- If asking for architecture advice, give concrete recommendations
- Be helpful and substantive, not generic

**If intent is "requirement" with conflicts:**
- Explain the conflicts found
- Suggest how to resolve them

**If intent is "general":**
- Engage in helpful project-related conversation
- Provide relevant context or suggestions

**If there's an error:**
- Explain what went wrong clearly
- Suggest next steps

## Format
- Be concise but substantive
- Use markdown for clarity when needed
- If you created multiple requirements, summarize them
- NEVER output meta-responses like "here are some options" - just respond directly
"""


async def response_node(state: RequirementState) -> dict:
    """
    Generate the final response to send to the user.

    Now includes:
    - Persona knowledge for specialized responses
    - User's original message for context
    - Better handling of different intent types
    """
    print(f"[DEBUG] response_node called, intent={state.get('intent')}, draft={bool(state.get('draft'))}")

    # If response already set (e.g., by rejection), use it
    if state.get("response"):
        print(f"[DEBUG] response_node: response already set")
        return {}

    logger.info("generating_response", channel_id=state.get("channel_id"))

    llm = get_llm_for_state(state, temperature=0.5)

    # Get persona knowledge
    persona_name = state.get("active_persona")
    persona_knowledge = get_persona_knowledge(persona_name, state)

    # Format draft info
    draft_str = "None"
    if state.get("draft"):
        draft = state["draft"]
        draft_str = f"Title: {draft.get('title')}\nType: {draft.get('issue_type')}\nDescription: {draft.get('description', '')[:200]}"

    # Format all drafts if complex
    all_drafts_str = "None"
    if state.get("all_drafts"):
        all_drafts = state["all_drafts"]
        all_drafts_str = "\n".join(
            f"- [{d.get('issue_type')}] {d.get('title')}"
            for d in all_drafts
        )

    # Format conflicts
    conflicts_str = "None"
    if state.get("conflicts"):
        conflicts_str = "\n".join(
            f"- {c.get('conflict_type')}: {c.get('description')}"
            for c in state["conflicts"]
        )

    prompt = ChatPromptTemplate.from_template(RESPONSE_PROMPT)
    messages = prompt.format_messages(
        user_message=state.get("message", ""),
        intent=state.get("intent", "unknown"),
        active_persona=persona_name or "Main Bot",
        draft=draft_str,
        all_drafts=all_drafts_str,
        conflicts=conflicts_str,
        jira_key=state.get("jira_issue_key") or "None",
        error=state.get("error") or "None",
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        return {"response": response.content}

    except Exception as e:
        logger.error("response_generation_failed", error=str(e))
        return {"response": "I've processed your request. Let me know if you need anything else."}


# =============================================================================
# No Response Node
# =============================================================================

async def no_response_node(state: RequirementState) -> dict:
    """
    Terminal node when bot decides not to respond.

    This is used when confidence is below threshold and bot stays silent.
    """
    logger.info(
        "no_response",
        channel_id=state.get("channel_id"),
        confidence=state.get("intent_confidence"),
    )
    return {"should_respond": False, "response": None}
