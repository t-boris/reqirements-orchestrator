"""Stage 2: Multi-intent classification and task extraction.

This module handles multi-intent classification for compound requests
(e.g., "check duplicates AND create stories").

Part of the modularized intent package (Phase 42).
"""
import json
import logging
from typing import Optional

from src.schemas.intent import (
    Intent, IntentResult, SuperMode, get_super_mode,
    TaskPlanProposal, TaskProposal,
)

logger = logging.getLogger(__name__)


async def _llm_classify_multi_intent(
    message: str,
    conversation_context: dict | None = None,
    active_draft: dict | None = None,
) -> TaskPlanProposal:
    """Use LLM to classify multiple intents from compound requests.

    When message contains conjunctions like "and", "also", "plus", this function
    extracts multiple distinct intents as a TaskPlanProposal.

    Args:
        message: User's current message text
        conversation_context: Full conversation history (messages + summary)
        active_draft: Active draft summary for context-aware classification

    Returns:
        TaskPlanProposal with tasks for each detected intent
    """
    from src.llm import get_llm

    llm = get_llm()

    # Build context string from conversation history
    context_str = ""
    if conversation_context:
        messages = conversation_context.get("messages", [])
        summary = conversation_context.get("summary")

        if summary:
            context_str += f"Conversation summary:\n{summary}\n\n"

        if messages:
            context_str += "Recent messages:\n"
            for msg in messages[-10:]:  # Last 10 messages for multi-intent context
                user = msg.get("user", "unknown")
                text = msg.get("text", "")
                if text:
                    context_str += f"[{user}]: {text}\n"
            context_str += "\n"

    prompt = f"""You are classifying user intent for a Slack bot. The user message may contain MULTIPLE distinct requests.

{f"CONVERSATION CONTEXT:{chr(10)}{context_str}" if context_str else ""}
CURRENT USER MESSAGE: "{message}"

When the user message contains multiple distinct requests (e.g., "check duplicates AND create stories"),
return ALL intents as a JSON array. Look for conjunctions: and, also, plus, then, after that.

AVAILABLE INTENTS:
- WORKITEM_CREATE: Create new work item
- TICKET_ACTION: Create items linked to existing ticket
- JIRA_COMMAND: Modify existing ticket fields
- JIRA_SEARCH: Search Jira for existing issues
- SYNC_REQUEST: Sync channel with Jira
- REVIEW: Analysis/feedback/discussion
- DISCUSSION: Greeting/casual
- DECISION: Recording a decision
- DRAFT_REFINE: Questions about draft structure
- DRAFT_TRANSFORM: Commands to change draft structure

RESPONSE FORMAT (JSON only):
{{
  "intents": [
    {{"intent": "INTENT_NAME", "confidence": 0.9, "title": "Human readable task title", "params": {{}}}},
    {{"intent": "INTENT_NAME", "confidence": 0.85, "title": "Human readable task title", "params": {{}}}}
  ],
  "multi_intent": true,
  "reasons": ["why multiple intents detected"]
}}

For single intent messages, return:
{{
  "intents": [{{"intent": "...", "confidence": ..., "title": "...", "params": {{}}}}],
  "multi_intent": false,
  "reasons": ["single intent explanation"]
}}

PARAMS can include:
- For JIRA_SEARCH: {{"search_query": "query"}}
- For TICKET_ACTION: {{"ticket_key": "SCRUM-123", "action_type": "create_stories"}}
- For JIRA_COMMAND: {{"ticket_key": "SCRUM-123", "field": "status", "value": "Done"}}

Respond with valid JSON only, no markdown code blocks."""

    try:
        result = await llm.chat(prompt)

        # Strip markdown code blocks if present
        result = result.strip()
        if result.startswith("```"):
            # Remove first line (```json or ```)
            lines = result.split("\n")
            result = "\n".join(lines[1:])
        if result.endswith("```"):
            result = result[:-3]
        result = result.strip()

        data = json.loads(result)

        intents_data = data.get("intents", [])
        is_multi = data.get("multi_intent", False)
        reasons = data.get("reasons", [])

        tasks = []
        for idx, item in enumerate(intents_data):
            intent_str = item.get("intent", "REVIEW").upper()
            if intent_str == "TICKET":
                intent_str = "WORKITEM_CREATE"

            try:
                intent = Intent(intent_str.lower())
            except ValueError:
                intent = Intent.REVIEW

            super_mode = get_super_mode(intent)

            task = TaskProposal(
                intent=intent,
                super_mode=super_mode,
                confidence=float(item.get("confidence", 0.8)),
                title=item.get("title", f"Task {idx + 1}"),
                params=item.get("params", {}),
                depends_on_indices=[],
            )
            tasks.append(task)

        return TaskPlanProposal(
            tasks=tasks,
            is_multi_intent=is_multi or len(tasks) > 1,
            low_confidence_signal=any(t.confidence < 0.7 for t in tasks),
            trigger_message=message,
            reasons=reasons,
        )

    except Exception as e:
        logger.warning(f"Multi-intent LLM classification failed: {e}, returning single-task fallback")
        # Fallback to single task with REVIEW intent
        return TaskPlanProposal(
            tasks=[TaskProposal(
                intent=Intent.REVIEW,
                super_mode=SuperMode.THINK,
                confidence=0.5,
                title="Review request",
                params={},
                depends_on_indices=[],
            )],
            is_multi_intent=False,
            low_confidence_signal=True,
            trigger_message=message,
            reasons=["multi-intent classification failed, fallback to REVIEW"],
        )


def _generate_task_title(result: IntentResult) -> str:
    """Generate human-readable task title from IntentResult."""
    titles = {
        Intent.WORKITEM_CREATE: "Create work item",
        Intent.TICKET_ACTION: f"Action on {result.ticket_key or 'ticket'}",
        Intent.JIRA_COMMAND: f"Update {result.command_field or 'field'}",
        Intent.JIRA_SEARCH: f"Search Jira{': ' + result.search_query if result.search_query else ''}",
        Intent.REVIEW: "Review/analysis",
        Intent.DISCUSSION: "Discussion",
        Intent.DECISION: result.decision_title_hint or "Record decision",
        Intent.DRAFT_REFINE: "Refine draft",
        Intent.DRAFT_TRANSFORM: f"Transform draft ({result.transform_operation or 'structure'})",
        Intent.SYNC_REQUEST: "Sync with Jira",
        Intent.CHANGE_REQUEST: "Change request",
    }
    return titles.get(result.intent, "Process request")


def _extract_intent_params(result: IntentResult) -> dict:
    """Extract intent-specific parameters from IntentResult."""
    params = {}
    if result.ticket_key:
        params["ticket_key"] = result.ticket_key
    if result.action_type:
        params["action_type"] = result.action_type
    if result.command_type:
        params["command_type"] = result.command_type
    if result.command_field:
        params["command_field"] = result.command_field
    if result.command_value:
        params["command_value"] = result.command_value
    if result.search_query:
        params["search_query"] = result.search_query
    if result.transform_operation:
        params["transform_operation"] = result.transform_operation
    if result.decision_type_hint:
        params["decision_type_hint"] = result.decision_type_hint
    if result.decision_title_hint:
        params["decision_title_hint"] = result.decision_title_hint
    if result.ops_subtype:
        params["ops_subtype"] = result.ops_subtype.value  # Serialize to string
    return params
