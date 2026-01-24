"""OPS node - operational mode for debugging and explaining.

Handles OPS intent with two subtypes:
- DEBUG: Triage failures, identify causes, suggest fixes/retry
- EXPLAIN: Show reasoning, policy traces, decision explanations

System operator perspective - not LLM chain-of-thought.

Phase 27.5: Enhanced explain mode with audit trail.
"""
import logging
from datetime import datetime
from typing import Optional

from src.schemas.intent import OpsSubtype
from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


async def build_explain_output(state: dict, channel_id: str, thread_ts: Optional[str] = None) -> str:
    """Build operator protocol explanation for /maro explain.

    Phase 27.5: Enhanced explain output including:
    - Intent detected with confidence
    - Current state/phase
    - Flow reasoning
    - Next steps
    - Recent audit trail

    Args:
        state: Current agent state dict.
        channel_id: Slack channel ID.
        thread_ts: Optional thread timestamp for thread-specific audit.

    Returns:
        Formatted explain output string.
    """
    from src.db import get_connection
    from src.db.audit_store import AuditStore

    sections = []

    # Intent chosen
    intent_result = state.get("intent_result", {})
    intent = intent_result.get("intent", "unknown")
    confidence = intent_result.get("confidence", 0)
    reasons = intent_result.get("reasons", [])

    sections.append(f"*Intent:* `{intent}` ({confidence:.0%} confident)")
    if reasons:
        sections.append(f"_Reasons:_ {', '.join(str(r) for r in reasons[:3])}")

    # Current state
    phase = state.get("phase", "unknown")
    pending_action = state.get("pending_action")
    workflow_step = state.get("workflow_step")

    sections.append(f"\n*State:* phase=`{phase}`")
    if pending_action:
        sections.append(f"Waiting for: `{pending_action}`")
    if workflow_step:
        sections.append(f"Workflow step: `{workflow_step}`")

    # Why this flow
    sections.append("\n*Flow reasoning:*")
    if intent in ("TICKET", "WORKITEM_CREATE"):
        sections.append("- User wants to create a work item")
        sections.append("- Routing to draft extraction + validation")
    elif intent == "REVIEW":
        sections.append("- User wants analysis without Jira action")
        sections.append("- Routing to review/discussion flow")
    elif intent == "DRAFT_REFINE":
        sections.append("- User asking about draft structure")
        sections.append("- Offering scope/type options")
    elif intent == "DISCUSS":
        sections.append("- User wants to discuss/chat")
        sections.append("- Routing to discussion flow")
    elif intent == "JIRA_SEARCH":
        sections.append("- User searching for existing Jira issues")
        sections.append("- Routing to search flow")
    elif intent == "OPS":
        sections.append("- User requesting operational insight")
        sections.append("- Routing to debug/explain flow")
    else:
        sections.append(f"- Intent `{intent}` detected")
        sections.append("- Routing to appropriate handler")

    # What happens next
    sections.append("\n*Next steps:*")
    if pending_action == "WAITING_APPROVAL":
        sections.append("1. User clicks Approve or Edit")
        sections.append("2. On approve: Create Jira ticket")
        sections.append("3. Post confirmation with link")
    elif pending_action == "WAITING_SCOPE_CHOICE":
        sections.append("1. User selects scope (Ticket/Review/Discussion)")
        sections.append("2. Re-route message with explicit intent")
    elif phase == "draft":
        sections.append("1. Continue extraction from message")
        sections.append("2. Validate draft completeness")
        sections.append("3. Show preview or ask questions")
    elif phase == "review":
        sections.append("1. Generate analysis")
        sections.append("2. Post review with optional actions")
    else:
        sections.append("1. Process user input")
        sections.append("2. Generate appropriate response")

    # Recent audit trail (Phase 27.5)
    try:
        async with get_connection() as conn:
            audit_store = AuditStore(conn)
            await audit_store.ensure_table()

            # Get audit entries - prefer thread-specific, fallback to channel
            if thread_ts:
                recent = await audit_store.get_for_thread(channel_id, thread_ts, limit=5)
            else:
                recent = await audit_store.get_for_channel(channel_id, limit=5)

            if recent:
                sections.append("\n*Recent actions:*")
                for entry in recent[:5]:
                    actor = f"<@{entry.actor_user_id}>"
                    outcome_emoji = ":white_check_mark:" if entry.outcome == "success" else ":x:"
                    sections.append(f"- {outcome_emoji} `{entry.action_type.value}` on `{entry.target_type}:{entry.target_id[:20]}` by {actor}")
    except Exception as e:
        logger.debug(f"Could not load audit trail: {e}")

    return "\n".join(sections)


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

CONVERSATION CONTEXT:
{context}

USER MESSAGE: "{message}"

INSTRUCTIONS:
Output your explanation in system/state machine terms:
1. Intent detected: What did you classify the user's request as?
2. Policy applied: What rules/criteria did you use?
3. Action executed: What did you do as a result?

Be concise and factual. This is system operator perspective, not LLM introspection.
Maximum 3-4 sentences.

Example format:
"Intent: [X]. Policy: [Y]. Action: [Z]."'''


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

    # Phase 27.5: For EXPLAIN, build structured output with audit trail
    if ops_subtype == OpsSubtype.EXPLAIN and channel_id:
        try:
            structured_output = await build_explain_output(state, channel_id, thread_ts)
            # If user asked a specific question, combine structured output with LLM response
            if latest_human_message and not any(
                kw in latest_human_message.lower()
                for kw in ["explain", "what did you", "why did you", "what's happening", "what are you doing"]
            ):
                # User asked a specific question - add structured output as context
                context_str += f"\n\n=== OPERATOR PROTOCOL ===\n{structured_output}"
            else:
                # User just wants explain mode - return structured output directly
                logger.info(f"OPS response generated (subtype={ops_subtype.value}, structured)")
                return {
                    "decision_result": {
                        "action": "ops",
                        "subtype": ops_subtype.value,
                        "message": structured_output,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                }
        except Exception as e:
            logger.warning(f"Could not build structured explain output: {e}")

    if not latest_human_message:
        logger.warning("No human message found for OPS node")
        if ops_subtype == OpsSubtype.DEBUG:
            response_text = "I don't see an error to debug. What went wrong?"
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
