"""Extraction node - updates draft from conversation messages.

Patch-style: Only updates fields that have new information.
Adds evidence links for traceability.
Uses answer matcher for responses to pending questions.
"""
import json
import logging
from typing import Any
from langchain_core.messages import HumanMessage, AIMessage

from src.schemas.state import AgentState, AgentPhase
from src.schemas.draft import TicketDraft, DraftConstraint, ConstraintStatus
from src.llm import get_llm
from src.skills.answer_matcher import match_answers

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = '''You are extracting requirements from a conversation to build a Jira ticket draft.

Current draft state:
{draft_json}

New message to process:
{message}

Extract any new information that should update the draft. Return a JSON object with ONLY the fields that have new information. Do not repeat existing values.

Fields you can update:
- title: Clear, concise ticket title
- problem: What problem we're solving
- proposed_solution: How we'll solve it
- acceptance_criteria: List of testable criteria (append new ones)
- constraints: List of {{"key", "value"}} technical decisions
- dependencies: List of external dependencies
- risks: List of potential risks

Return empty object {{}} if no new information to extract.

IMPORTANT: Only extract factual information stated in the message. Do not invent or assume.

JSON response:'''


async def extraction_node(state: AgentState) -> dict[str, Any]:
    """Extract requirements from latest message and patch draft.

    - Processes only the most recent human message
    - Uses answer matcher if pending questions exist
    - Uses LLM to identify new information
    - Patches draft with extracted fields
    - Adds evidence link for traceability
    - Increments step_count

    Returns partial state update.
    """
    messages = state.get("messages", [])
    draft = state.get("draft") or TicketDraft()
    step_count = state.get("step_count", 0)
    thread_ts = state.get("thread_ts", "")
    channel_id = state.get("channel_id", "")
    pending_questions = state.get("pending_questions")

    # Find most recent human message
    latest_human = None
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            latest_human = msg
            break

    if not latest_human:
        logger.debug("No human message to extract from")
        return {"step_count": step_count + 1}

    message_text = latest_human.content if isinstance(latest_human.content, str) else str(latest_human.content)

    # If we have pending questions, use answer matcher first
    answer_match_result = None
    if pending_questions and pending_questions.get("questions"):
        try:
            answer_match_result = await match_answers(
                questions=pending_questions.get("questions", []),
                user_response=message_text,
                expected_fields=pending_questions.get("expected_fields"),
            )
            logger.info(
                "Answer matching completed",
                extra={
                    "matched": len(answer_match_result.matches),
                    "unanswered": len(answer_match_result.unanswered_questions),
                    "all_answered": answer_match_result.all_answered,
                }
            )
        except Exception as e:
            logger.warning(f"Answer matching failed, falling back to extraction: {e}")

    # Prepare prompt
    draft_json = draft.model_dump_json(exclude={"evidence_links", "created_at", "updated_at"})
    prompt = EXTRACTION_PROMPT.format(
        draft_json=draft_json,
        message=message_text,
    )

    # Call LLM for extraction
    try:
        llm = get_llm()
        result = await llm.chat(prompt)
        response_text = result.content.strip()

        # Parse JSON response
        # Handle markdown code blocks
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        extracted = json.loads(response_text) if response_text and response_text != "{}" else {}

        if extracted:
            logger.info(
                "Extracted fields from message",
                extra={
                    "fields": list(extracted.keys()),
                    "thread_ts": thread_ts,
                }
            )

            # Handle list fields (append, don't replace)
            list_fields = ["acceptance_criteria", "dependencies", "risks"]
            for field in list_fields:
                if field in extracted and isinstance(extracted[field], list):
                    existing = getattr(draft, field, [])
                    extracted[field] = existing + extracted[field]

            # Handle constraints specially (list of dicts)
            if "constraints" in extracted:
                existing_constraints = draft.constraints
                for c in extracted["constraints"]:
                    if isinstance(c, dict) and "key" in c and "value" in c:
                        existing_constraints.append(DraftConstraint(
                            key=c["key"],
                            value=c["value"],
                            status=ConstraintStatus.PROPOSED,
                            source_message_ts=getattr(latest_human, "id", None),
                        ))
                extracted["constraints"] = existing_constraints

            # Patch draft
            draft.patch(**{k: v for k, v in extracted.items() if k not in ["constraints"] or k == "constraints"})

            # Add evidence link
            for field in extracted.keys():
                draft.add_evidence(
                    message_ts=getattr(latest_human, "id", "") or "",
                    thread_ts=thread_ts,
                    channel_id=channel_id,
                    field_updated=field,
                    text_preview=message_text[:100],
                )
        else:
            logger.debug("No new information extracted")

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse extraction response: {e}")
    except Exception as e:
        logger.error(f"Extraction failed: {e}")

    # Build state update
    state_update = {
        "draft": draft,
        "step_count": step_count + 1,
        "phase": AgentPhase.COLLECTING,  # Stay in collecting after extraction
    }

    # Include answer match result for decision node
    if answer_match_result:
        state_update["answer_match_result"] = {
            "matches": [m.model_dump() for m in answer_match_result.matches],
            "unanswered_questions": answer_match_result.unanswered_questions,
            "all_answered": answer_match_result.all_answered,
        }
        # Clear pending questions if all answered
        if answer_match_result.all_answered:
            state_update["pending_questions"] = None

    return state_update
