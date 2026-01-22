"""OPS node - operational mode for debugging and explaining.

Handles OPS intent with two subtypes:
- DEBUG: Triage failures, identify causes, suggest fixes/retry
- EXPLAIN: Show reasoning, policy traces, decision explanations

System operator perspective - not LLM chain-of-thought.
"""
import logging
from datetime import datetime

from src.schemas.intent import OpsSubtype
from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


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
        context_str += f"\n\nLast draft state: {draft.get('phase', 'unknown')}"
        context_str += f"\nDraft type: {draft.get('issue_type', 'unknown')}"

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
