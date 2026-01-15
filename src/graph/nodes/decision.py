"""Decision node - routes to ASK, PREVIEW, or READY_TO_CREATE.

Prioritizes most impactful issues first.
Smart batching: immediate if urgent, else batch related questions.
Re-ask logic: max 2 re-asks before proceeding with partial info.
Duplicate detection: searches for similar tickets before preview.

EXECUTE is deferred to Phase 7 - only sets state to READY_TO_CREATE.
"""
import logging
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

from src.schemas.state import AgentState, AgentPhase
from src.schemas.draft import TicketDraft

logger = logging.getLogger(__name__)

# Max re-ask attempts before proceeding with partial info
MAX_REASK_COUNT = 2


class DecisionResult(BaseModel):
    """Result of decision node processing."""
    action: Literal["ask", "preview", "ready_to_create"]
    questions: list[str] = Field(default_factory=list)  # For ASK action
    reason: str = ""  # Why this decision
    is_reask: bool = False  # True if re-asking unanswered questions
    reask_count: int = 0  # How many times we've re-asked
    potential_duplicates: list[dict] = Field(default_factory=list)  # Similar tickets found
    bound_ticket: Optional[str] = None  # Existing ticket this thread is bound to


def prioritize_issues(
    missing_fields: list[str],
    conflicts: list[str],
    suggestions: list[str],
) -> list[str]:
    """Prioritize issues by impact.

    Order: conflicts (blockers) > missing required > suggestions (nice-to-have)
    Returns list of questions/issues, most impactful first.
    """
    questions = []

    # Conflicts are blockers - ask first
    for conflict in conflicts:
        questions.append(f"I found a conflict: {conflict}. How should we resolve this?")

    # Missing required fields
    field_questions = {
        "title": "What should be the title/summary for this ticket?",
        "problem": "What problem are we trying to solve?",
        "acceptance_criteria": "What are the acceptance criteria? How will we know this is done?",
    }
    for field in missing_fields:
        # Extract base field name
        base_field = field.split(" ")[0].strip("()")
        if base_field in field_questions:
            questions.append(field_questions[base_field])
        else:
            questions.append(f"Please provide: {field}")

    return questions


def batch_questions(questions: list[str], max_batch: int = 3) -> list[str]:
    """Batch related questions together.

    Returns at most max_batch questions to avoid overwhelming user.
    Most impactful questions first (already prioritized).
    """
    return questions[:max_batch]


async def _explain_duplicate_match(
    draft: TicketDraft,
    duplicate: dict,
) -> str:
    """Generate concise explanation of why duplicate matches draft.

    Uses LLM to identify matching aspects: feature area, action, entities.

    Returns:
        Explanation like "same feature area (notifications), same main action (scheduling)"
        or empty string on error.
    """
    try:
        from src.llm import get_llm

        llm = get_llm()

        prompt = f"""Compare these two ticket descriptions and explain why they might be related in ONE SHORT phrase (max 80 chars).

Draft ticket title: "{draft.title}"
Draft problem: "{draft.problem[:200] if draft.problem else 'Not specified'}"

Existing ticket: "{duplicate.get('summary', '')}"

Focus on what they have in common:
- Same feature area? (e.g., "same feature area (notifications)")
- Same action type? (e.g., "same action (scheduling)")
- Same entities? (e.g., "same entities (user accounts)")

Respond with ONLY a short phrase explaining the match. Examples:
- "same feature area (notifications), same action (scheduling)"
- "both about user authentication"
- "related to payment processing"

If they don't seem related, respond with empty string."""

        result = await llm.chat(prompt)

        # Clean and validate response (llm.chat returns str directly)
        explanation = result.strip().strip('"').strip()

        # Truncate if too long
        if len(explanation) > 100:
            explanation = explanation[:97] + "..."

        # Reject if it looks like refusal or error
        if any(word in explanation.lower() for word in ["sorry", "cannot", "don't", "i am", "i'm"]):
            return ""

        return explanation

    except Exception as e:
        logger.warning(f"Failed to generate match explanation: {e}")
        return ""


async def _search_for_duplicates(draft: TicketDraft | None) -> list[dict]:
    """Search for potential duplicate tickets.

    Returns list of {key, summary, url, status, assignee, updated, match_reason} dicts.
    For the best match (first), generates LLM explanation of why it matches.
    Fails gracefully - returns empty list on any error.
    """
    if not draft or not draft.title:
        return []

    try:
        from src.config.settings import get_settings
        from src.jira.client import JiraService
        from src.skills.jira_search import search_similar_to_draft

        settings = get_settings()
        jira_service = JiraService(settings)

        try:
            result = await search_similar_to_draft(draft, jira_service, limit=5)

            # Convert to display format with enhanced metadata
            duplicates = []
            for i, issue in enumerate(result.issues[:5]):  # Keep up to 5 for "show more"
                dup = {
                    "key": issue.key,
                    "summary": issue.summary,
                    "url": issue.url,
                    "status": issue.status,
                    "assignee": issue.assignee,
                    "updated": issue.updated,
                    "match_reason": "",
                }
                duplicates.append(dup)

            # Generate match explanation for best match only
            if duplicates:
                match_reason = await _explain_duplicate_match(draft, duplicates[0])
                duplicates[0]["match_reason"] = match_reason

                logger.info(
                    "Found potential duplicates",
                    extra={
                        "count": len(duplicates),
                        "draft_title": draft.title[:50],
                        "best_match": duplicates[0]["key"],
                        "match_reason": match_reason,
                    },
                )

            return duplicates

        finally:
            await jira_service.close()

    except Exception as e:
        # Don't fail the workflow if duplicate search fails
        logger.warning(
            "Failed to search for duplicates",
            extra={"error": str(e)},
        )
        return []


async def decision_node(state: AgentState) -> dict[str, Any]:
    """Decide next action: ASK, PREVIEW, or READY_TO_CREATE.

    Logic:
    0. If thread already bound to a ticket -> PREVIEW (skip duplicate detection)
    1. If validation passed (is_valid=True) -> PREVIEW
    2. If conflicts exist -> ASK (prioritize conflicts)
    3. If missing fields -> ASK (batch questions)
    4. If approved -> READY_TO_CREATE
    5. Check for unanswered questions from previous ask -> RE-ASK (max 2 times)
    6. After max re-asks -> proceed with partial info (PREVIEW)

    Returns partial state update with decision result.
    """
    draft = state.get("draft")
    validation_report = state.get("validation_report", {})
    step_count = state.get("step_count", 0)
    phase = state.get("phase", AgentPhase.COLLECTING)
    pending_questions = state.get("pending_questions")
    answer_match_result = state.get("answer_match_result", {})

    # Check thread binding FIRST - if thread is already bound to a ticket,
    # skip duplicate detection entirely (Phase 13.1 fix)
    thread_ts = state.get("thread_ts")
    channel_id = state.get("channel_id")

    if thread_ts and channel_id:
        from src.slack.thread_bindings import get_binding_store

        binding_store = get_binding_store()
        binding = await binding_store.get_binding(channel_id, thread_ts)

        if binding:
            logger.info(
                "Thread already bound to ticket, skipping duplicate detection",
                extra={
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                    "bound_ticket": binding.issue_key,
                }
            )
            # Skip duplicate detection - go straight to preview with bound ticket info
            return {
                "step_count": step_count + 1,
                "phase": AgentPhase.AWAITING_USER,
                "pending_questions": None,
                "decision_result": DecisionResult(
                    action="preview",
                    reason=f"Thread bound to {binding.issue_key}",
                    bound_ticket=binding.issue_key,
                ).model_dump(),
            }

    # Check if already approved (would be set by approval handler)
    if phase == AgentPhase.READY_TO_CREATE:
        logger.info("Draft already approved, ready to create")
        return {
            "step_count": step_count + 1,
            "decision_result": DecisionResult(
                action="ready_to_create",
                reason="Draft approved by user",
            ).model_dump(),
        }

    # Check for unanswered questions from previous ask
    unanswered = answer_match_result.get("unanswered_questions", [])
    current_reask_count = pending_questions.get("re_ask_count", 0) if pending_questions else 0

    if unanswered and current_reask_count < MAX_REASK_COUNT:
        # Re-ask unanswered questions
        new_reask_count = current_reask_count + 1
        batched = batch_questions(unanswered)

        logger.info(
            "Re-asking unanswered questions",
            extra={
                "unanswered": len(unanswered),
                "reask_count": new_reask_count,
                "max_reask": MAX_REASK_COUNT,
            }
        )

        # Update pending_questions with incremented re_ask_count
        updated_pending = dict(pending_questions) if pending_questions else {}
        updated_pending["questions"] = batched
        updated_pending["re_ask_count"] = new_reask_count

        return {
            "step_count": step_count + 1,
            "phase": AgentPhase.AWAITING_USER,
            "pending_questions": updated_pending,
            "decision_result": DecisionResult(
                action="ask",
                questions=batched,
                reason=f"Re-asking {len(batched)} unanswered questions (attempt {new_reask_count}/{MAX_REASK_COUNT})",
                is_reask=True,
                reask_count=new_reask_count,
            ).model_dump(),
        }
    elif unanswered and current_reask_count >= MAX_REASK_COUNT:
        # Max re-asks reached, proceed with partial info
        logger.info(
            "Max re-asks reached, proceeding with partial info",
            extra={
                "unanswered": len(unanswered),
                "reask_count": current_reask_count,
            }
        )
        # Clear pending questions and proceed to preview
        return {
            "step_count": step_count + 1,
            "phase": AgentPhase.AWAITING_USER,
            "pending_questions": None,
            "decision_result": DecisionResult(
                action="preview",
                reason=f"Proceeding with partial info after {MAX_REASK_COUNT} re-asks ({len(unanswered)} questions unanswered)",
            ).model_dump(),
        }

    # Get validation details
    is_valid = validation_report.get("is_valid", False)
    missing_fields = validation_report.get("missing_fields", [])
    conflicts = validation_report.get("conflicts", [])
    suggestions = validation_report.get("suggestions", [])

    # Decision logic
    if is_valid and not conflicts:
        # Ready for preview - check for duplicates first
        logger.info("Draft valid, checking for potential duplicates before preview")

        potential_duplicates = await _search_for_duplicates(draft)

        dup_reason = "Draft meets minimum requirements"
        if potential_duplicates:
            dup_reason = f"Draft meets requirements. Found {len(potential_duplicates)} potential duplicate(s)."

        return {
            "step_count": step_count + 1,
            "phase": AgentPhase.AWAITING_USER,
            "pending_questions": None,  # Clear any pending
            "decision_result": DecisionResult(
                action="preview",
                reason=dup_reason,
                potential_duplicates=potential_duplicates,
            ).model_dump(),
        }

    # Need to ask questions
    questions = prioritize_issues(missing_fields, conflicts, suggestions)
    batched = batch_questions(questions)

    logger.info(
        "Asking user for more information",
        extra={
            "total_issues": len(questions),
            "batch_size": len(batched),
        }
    )

    return {
        "step_count": step_count + 1,
        "phase": AgentPhase.AWAITING_USER,
        "decision_result": DecisionResult(
            action="ask",
            questions=batched,
            reason=f"Need {len(missing_fields)} fields, {len(conflicts)} conflicts to resolve",
        ).model_dump(),
    }


def get_decision_action(state: AgentState) -> Literal["ask", "preview", "ready"]:
    """Get decision action from state for routing.

    Use in graph conditional edges.
    """
    result = state.get("decision_result", {})
    action = result.get("action", "ask")
    if action == "ready_to_create":
        return "ready"
    return action
