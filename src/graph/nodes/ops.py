"""OPS node - operational mode for debugging, explaining, and expanding.

Handles OPS intent with three subtypes:
- DEBUG: Triage failures, identify causes, suggest fixes/retry
- EXPLAIN: Show bot's reasoning, policy traces (about bot's actions)
- EXPAND: Show object details (decision rationale, alternatives, consequences)

System operator perspective - not LLM chain-of-thought.

Phase 27.5: Enhanced explain mode with audit trail.
Phase 38-06: Uses ContextBuilder for structured explain context.
Phase 41+: EXPAND subtype for showing domain object details.
"""
import logging
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from src.schemas.intent import OpsSubtype

if TYPE_CHECKING:
    from src.schemas.decision import Decision
from src.schemas.state import AgentState
from src.context import ContextSpec, build_context

logger = logging.getLogger(__name__)


# Note: build_explain_output() removed in Phase 38-06
# Replaced by ContextBuilder which provides structured context with === sections


DEBUG_PROMPT = '''You are MARO in DEBUG mode. A user is asking about an error or failure.

CONVERSATION CONTEXT:
{context}

USER MESSAGE: "{message}"

INSTRUCTIONS:
1. Identify what failed (be specific about the operation)
2. Determine probable cause from the context
3. Suggest a fix or offer to retry if applicable

Respond in system operator style:
- Use technical terms but be concise
- Structure as: [What failed] -> [Probable cause] -> [Suggested action]
- If you can retry the operation, offer to do so
- Maximum 3-4 sentences

Example format:
"Failed: [operation]. Cause: [reason]. Fix: [action]."'''


EXPLAIN_PROMPT = '''You are MARO in EXPLAIN mode. A user is asking about your reasoning or decisions.

{context}

USER MESSAGE: "{message}"

INSTRUCTIONS:
Using the structured context above, explain what happened:
1. What decisions or reviews are active in this thread?
2. What was the most recent action taken?
3. Why was that action chosen?

Use the SYSTEM STATE section for decisions and reviews.
Use the CONVERSATION section to understand the flow.
Use the RETRIEVED section for any documents or attachments considered.

Be concise and factual. This is system operator perspective, not LLM introspection.
Maximum 4-5 sentences.

If you see no relevant context, say so honestly and suggest what the user can ask about.'''


EXPAND_PROMPT = '''You are MARO showing details about a recorded decision.

DECISION:
Title: {title}
Type: {decision_type}
Status: {status}

Rationale: {rationale}

Alternatives Considered: {alternatives}

Consequences: {consequences}

USER MESSAGE: "{message}"

INSTRUCTIONS:
Explain this decision in clear terms. The user wants to understand:
1. What was decided and why
2. What alternatives were considered (if any)
3. What the consequences or implications are

Be informative but concise. Focus on the decision's content, not on bot mechanics.
If specific sections are empty, skip them gracefully.'''


async def ops_node(state: AgentState) -> dict:
    """LangGraph node for OPS flow.

    Handles DEBUG (error triage) and EXPLAIN (policy trace) subtypes.
    Provides operational insight in system operator style.

    Args:
        state: Current AgentState dict

    Returns:
        Partial state update with decision_result containing ops response
    """
    from langchain_core.messages import HumanMessage
    from src.llm import get_llm

    # Get intent result to determine subtype
    intent_result = state.get("intent_result", {})
    ops_subtype_str = intent_result.get("ops_subtype")

    # Parse subtype
    if ops_subtype_str == "debug" or ops_subtype_str == OpsSubtype.DEBUG:
        ops_subtype = OpsSubtype.DEBUG
    elif ops_subtype_str == "explain" or ops_subtype_str == OpsSubtype.EXPLAIN:
        ops_subtype = OpsSubtype.EXPLAIN
    elif ops_subtype_str == "expand" or ops_subtype_str == OpsSubtype.EXPAND:
        ops_subtype = OpsSubtype.EXPAND
    else:
        # Default to DEBUG if subtype not specified
        ops_subtype = OpsSubtype.DEBUG
        logger.warning(f"OPS subtype not specified, defaulting to DEBUG")

    # Get latest human message
    messages = state.get("messages", [])
    latest_human_message = None

    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human_message = msg.content
            break

    # Build context from conversation
    context_str = ""
    conversation_context = state.get("conversation_context", {})
    if conversation_context:
        conv_messages = conversation_context.get("messages", [])
        if conv_messages:
            context_str = "\n".join([
                f"[{m.get('user', 'unknown')}]: {m.get('text', '')}"
                for m in conv_messages[-10:]  # Last 10 messages
                if m.get('text')
            ])

    # Add recent agent decisions to context for EXPLAIN
    draft = state.get("draft")
    if draft and ops_subtype == OpsSubtype.EXPLAIN:
        # draft is a TicketDraft Pydantic model, use attribute access
        phase = state.get("phase", "unknown")
        issue_type = getattr(draft, "issue_type", "unknown") if draft else "unknown"
        context_str += f"\n\nLast draft phase: {phase}"
        context_str += f"\nDraft type: {issue_type}"

    # Add review_artifact if present (Architecture Decisions)
    review_artifact = state.get("review_artifact")
    if review_artifact and ops_subtype == OpsSubtype.EXPLAIN:
        topic = review_artifact.get("topic", "unknown")
        decisions = review_artifact.get("decisions", [])
        if decisions:
            context_str += "\n\n=== ARCHITECTURE DECISIONS IN THIS THREAD ==="
            for i, dec in enumerate(decisions, 1):
                dec_topic = dec.get("topic", "")
                dec_text = dec.get("decision", "")
                context_str += f"\n{i}. {dec_topic}: {dec_text}"
        elif topic:
            summary = review_artifact.get("summary", "")[:500]
            context_str += f"\n\n=== ARCHITECTURE DECISION ===\nTopic: {topic}\n{summary}"

    # Also check thread_state for decisions
    thread_state = state.get("thread_state")
    if thread_state and ops_subtype == OpsSubtype.EXPLAIN:
        if hasattr(thread_state, "review_artifact") and thread_state.review_artifact:
            artifact = thread_state.review_artifact
            if isinstance(artifact, dict):
                topic = artifact.get("topic", "")
                decisions = artifact.get("decisions", [])
                if decisions and "=== ARCHITECTURE DECISIONS" not in context_str:
                    context_str += "\n\n=== THREAD DECISIONS ==="
                    for i, dec in enumerate(decisions, 1):
                        context_str += f"\n{i}. {dec.get('topic', '')}: {dec.get('decision', '')}"

    # Load recent decisions from database for this channel
    channel_id = state.get("channel_id")
    thread_ts = state.get("thread_ts")

    # Handle EXPAND: find decision from thread context and return rich card
    if ops_subtype == OpsSubtype.EXPAND:
        decision_id = await _find_decision_in_context(state)
        if decision_id:
            # Generate additional context via LLM
            decision = await _get_decision(decision_id)
            if decision:
                try:
                    llm = get_llm()
                    prompt = EXPAND_PROMPT.format(
                        title=decision.title or "Untitled",
                        decision_type=decision.decision_type.value if decision.decision_type else "general",
                        status=decision.status.value if decision.status else "unknown",
                        rationale=decision.rationale or "Not specified",
                        alternatives=decision.alternatives or "Not specified",
                        consequences=decision.consequences or "Not specified",
                        message=latest_human_message or "Show decision details",
                    )
                    response_text = await llm.chat(prompt)
                except Exception as e:
                    logger.warning(f"LLM call failed generating expand context: {e}")
                    response_text = ""

                return {
                    "decision_result": {
                        "action": "ops",
                        "subtype": ops_subtype.value,
                        "message": response_text,
                        "decision_id": str(decision_id),
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                }
        # If no decision found, fall through to generate helpful message
        logger.info("EXPAND requested but no decision found in context")

    if channel_id and ops_subtype == OpsSubtype.EXPLAIN and "=== ARCHITECTURE DECISIONS" not in context_str:
        try:
            from src.db import get_connection

            async def fetch_decisions():
                async with get_connection() as conn:
                    async with conn.cursor() as cur:
                        await cur.execute(
                            """
                            SELECT topic, decision_text
                            FROM channel_decisions
                            WHERE channel_id = %s
                            ORDER BY created_at DESC
                            LIMIT 5
                            """,
                            (channel_id,),
                        )
                        return await cur.fetchall()

            recent_decisions = await fetch_decisions()
            if recent_decisions:
                context_str += "\n\n=== RECENT CHANNEL DECISIONS ==="
                for topic, decision_text in recent_decisions:
                    context_str += f"\n• {topic}: {decision_text[:200]}"
        except Exception as e:
            logger.debug(f"Could not load channel decisions: {e}")

    # Phase 38-06: For EXPLAIN, use ContextBuilder for structured context
    if ops_subtype == OpsSubtype.EXPLAIN and channel_id:
        try:
            # Build structured context using ContextSpec.for_ops_explain()
            spec = ContextSpec.for_ops_explain(channel_id, thread_ts or "")
            packet = await build_context(spec)

            # Use packet.to_prompt() for structured context with === sections
            structured_context = packet.to_prompt()

            if structured_context and not packet.is_empty:
                # Replace ad-hoc context with structured context
                context_str = structured_context
                logger.debug(f"Built structured explain context: {packet.total_tokens} tokens")
            else:
                # Fallback to existing context if ContextBuilder returns empty
                logger.debug("ContextBuilder returned empty packet, using fallback context")

        except Exception as e:
            logger.warning(f"Could not build structured explain context: {e}")

    if not latest_human_message:
        logger.warning("No human message found for OPS node")
        if ops_subtype == OpsSubtype.DEBUG:
            response_text = "I don't see an error to debug. What went wrong?"
        elif ops_subtype == OpsSubtype.EXPAND:
            response_text = "I couldn't find a decision to expand. Which decision would you like to see details for?"
        else:
            response_text = "I can explain my reasoning, but I need context. What would you like me to explain?"
    else:
        try:
            llm = get_llm()

            if ops_subtype == OpsSubtype.DEBUG:
                prompt = DEBUG_PROMPT.format(
                    context=context_str or "No prior context available.",
                    message=latest_human_message
                )
            elif ops_subtype == OpsSubtype.EXPAND:
                # EXPAND without decision found - provide helpful response
                prompt = f"""The user asked to expand/show details about something, but no specific decision was found in context.

Context: {context_str or "No prior context available."}
User message: "{latest_human_message}"

Please explain that you couldn't find a specific decision to expand. If there are decisions visible in the context, mention them. Otherwise, suggest how the user can specify which decision they want to see."""
            else:  # EXPLAIN
                prompt = EXPLAIN_PROMPT.format(
                    context=context_str or "No prior context available.",
                    message=latest_human_message
                )

            response_text = await llm.chat(prompt)

        except Exception as e:
            logger.warning(f"LLM call failed in OPS node: {e}")
            if ops_subtype == OpsSubtype.DEBUG:
                response_text = f"Debug mode: Unable to analyze the error. Please describe what went wrong."
            elif ops_subtype == OpsSubtype.EXPAND:
                response_text = f"Expand mode: Unable to find decision details. Please specify which decision you want to see."
            else:
                response_text = f"Explain mode: Unable to generate explanation. Please try again."

    logger.info(f"OPS response generated (subtype={ops_subtype.value})")

    return {
        "decision_result": {
            "action": "ops",
            "subtype": ops_subtype.value,
            "message": response_text,
            "timestamp": datetime.utcnow().isoformat(),
        }
    }


async def _find_decision_in_context(state: AgentState) -> Optional[str]:
    """Find decision ID from thread context or state.

    Looks in multiple places:
    1. Thread context (anchor_type=decision)
    2. review_artifact with decision ID
    3. Thread binding's decision_id

    Args:
        state: Current AgentState

    Returns:
        Decision ID (UUID string) if found, None otherwise
    """
    # 1. Check thread_context for decision anchor
    thread_context = state.get("thread_context")
    if thread_context:
        anchor_type = getattr(thread_context, "anchor_type", None)
        if anchor_type and hasattr(anchor_type, "value") and anchor_type.value == "decision":
            object_id = getattr(thread_context, "object_id", None)
            if object_id:
                logger.debug(f"Found decision from thread_context: {object_id}")
                return str(object_id)

        # Check decision attribute directly
        decision = getattr(thread_context, "decision", None)
        if decision:
            decision_id = getattr(decision, "id", None)
            if decision_id:
                logger.debug(f"Found decision from thread_context.decision: {decision_id}")
                return str(decision_id)

    # 2. Check review_artifact
    review_artifact = state.get("review_artifact")
    if review_artifact and isinstance(review_artifact, dict):
        decision_id = review_artifact.get("decision_id")
        if decision_id:
            logger.debug(f"Found decision from review_artifact: {decision_id}")
            return str(decision_id)

    # 3. Check thread binding
    channel_id = state.get("channel_id")
    thread_ts = state.get("thread_ts")
    if channel_id and thread_ts:
        try:
            from src.slack.thread_bindings import get_thread_binding

            binding = await get_thread_binding(channel_id, thread_ts)
            if binding and hasattr(binding, "decision_id") and binding.decision_id:
                logger.debug(f"Found decision from thread binding: {binding.decision_id}")
                return str(binding.decision_id)
        except Exception as e:
            logger.debug(f"Could not check thread binding: {e}")

    return None


async def _get_decision(decision_id: str) -> Optional["Decision"]:
    """Fetch decision from database.

    Args:
        decision_id: UUID string of the decision

    Returns:
        Decision object if found, None otherwise
    """
    from src.schemas.decision import Decision

    try:
        from src.db.decision_store import DecisionStore

        async with DecisionStore() as store:
            decision = await store.get(decision_id)
            return decision
    except Exception as e:
        logger.warning(f"Could not fetch decision {decision_id}: {e}")
        return None
