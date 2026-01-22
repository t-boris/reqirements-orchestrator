"""Decision node - routes to ASK, PREVIEW, PREFLIGHT_REQUIRED, or READY_TO_CREATE.

Prioritizes most impactful issues first.
Smart batching: immediate if urgent, else batch related questions.
Re-ask logic: max 2 re-asks before proceeding with partial info.
Duplicate detection: searches for similar tickets before preview.
Preflight: blocks creation on EXACT_MATCH (>85% confidence) until user chooses.

EXECUTE is deferred to Phase 7 - only sets state to READY_TO_CREATE.
"""
import logging
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field

from src.schemas.state import AgentState, AgentPhase
from src.schemas.draft import TicketDraft
from src.schemas.preflight import DuplicateMatch, PreflightResult

logger = logging.getLogger(__name__)

# Max re-ask attempts before proceeding with partial info
MAX_REASK_COUNT = 2


class DecisionResult(BaseModel):
    """Result of decision node processing."""
    action: Literal["ask", "preview", "ready_to_create", "preflight_required", "draft_refine"]
    questions: list[str] = Field(default_factory=list)  # For ASK action
    reason: str = ""  # Why this decision
    is_reask: bool = False  # True if re-asking unanswered questions
    reask_count: int = 0  # How many times we've re-asked
    potential_duplicates: list[dict] = Field(default_factory=list)  # Similar tickets found
    bound_ticket: Optional[str] = None  # Existing ticket this thread is bound to
    preflight_result: Optional[dict] = None  # PreflightResult dict for blocking duplicates
    refinement_prompt: Optional[str] = None  # For DRAFT_REFINE: question to ask user


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


def _compute_confidence_score(draft: TicketDraft, duplicate: dict) -> float:
    """Compute confidence score for a duplicate match.

    Uses multiple signals to determine confidence:
    - Title similarity (word overlap)
    - Problem description similarity
    - Same status (lower confidence if already done)

    Args:
        draft: The draft ticket being created.
        duplicate: Dict with key, summary, status, etc.

    Returns:
        Confidence score from 0.0 to 1.0.
    """
    score = 0.0

    # Normalize strings for comparison
    draft_title = (draft.title or "").lower().strip()
    draft_problem = (draft.problem or "").lower().strip()
    dup_summary = (duplicate.get("summary") or "").lower().strip()

    if not draft_title or not dup_summary:
        return 0.0

    # Title word overlap (up to 0.5)
    draft_words = set(draft_title.split())
    dup_words = set(dup_summary.split())

    # Remove common words
    stop_words = {"the", "a", "an", "is", "are", "to", "for", "and", "or", "as", "in", "on", "at", "with"}
    draft_words = draft_words - stop_words
    dup_words = dup_words - stop_words

    if draft_words and dup_words:
        overlap = len(draft_words & dup_words)
        max_possible = max(len(draft_words), len(dup_words))
        title_score = (overlap / max_possible) * 0.5
        score += title_score

    # Problem description overlap (up to 0.3)
    if draft_problem:
        problem_words = set(draft_problem.split()) - stop_words
        if problem_words:
            dup_all_words = dup_words | set(duplicate.get("description", "").lower().split())
            overlap = len(problem_words & dup_all_words)
            max_possible = max(len(problem_words), len(dup_all_words)) if dup_all_words else len(problem_words)
            problem_score = (overlap / max_possible) * 0.3 if max_possible > 0 else 0.0
            score += problem_score

    # Boost for active tickets (up to 0.2)
    status = (duplicate.get("status") or "").lower()
    if status in ("to do", "open", "new", "in progress", "in review"):
        score += 0.2
    elif status in ("done", "closed", "resolved"):
        # Lower confidence for already done tickets
        score += 0.05

    return min(score, 1.0)


async def _search_channel_registry(
    draft: TicketDraft,
    channel_id: str,
) -> list[dict]:
    """Search channel's WorkItem registry for duplicates.

    Channel-first duplicate detection - checks local truth before remote.
    This reflects the Git model: check local (channel) before remote (Jira).

    Args:
        draft: The draft ticket being created.
        channel_id: The channel to search in.

    Returns:
        List of matching workitems as dicts with confidence scores.
    """
    try:
        from src.db import get_connection
        from src.db.workitem_store import WorkItemStore
        from src.db.models import WorkItemStatus

        duplicates = []

        async with get_connection() as conn:
            store = WorkItemStore(conn)
            workitems = await store.list_by_channel(
                channel_id,
                status=[WorkItemStatus.DRAFT, WorkItemStatus.ACTIVE],
                limit=50,
            )

            draft_title = (draft.title or "").lower()
            draft_problem = (draft.problem or "").lower()

            for item in workitems:
                confidence = _compute_channel_similarity(
                    draft_title,
                    draft_problem,
                    (item.summary or "").lower(),
                    (item.description or "").lower(),
                )

                if confidence >= 0.5:  # Threshold for channel matches
                    duplicates.append({
                        "workitem_id": item.id,
                        "jira_key": item.jira_key,
                        "key": item.jira_key or item.id[:8],
                        "summary": item.summary,
                        "status": item.status.value,
                        "confidence": confidence,
                        "source": "channel",
                        "match_reason": "",
                    })

        # Sort by confidence
        duplicates.sort(key=lambda x: x["confidence"], reverse=True)
        return duplicates[:5]  # Top 5

    except Exception as e:
        logger.warning(f"Failed to search channel registry: {e}")
        return []


def _compute_channel_similarity(
    draft_title: str,
    draft_problem: str,
    item_summary: str,
    item_description: str,
) -> float:
    """Compute similarity score between draft and existing item.

    Used for channel-first duplicate detection.

    Args:
        draft_title: Draft title (lowercased)
        draft_problem: Draft problem statement (lowercased)
        item_summary: Existing item summary (lowercased)
        item_description: Existing item description (lowercased)

    Returns:
        Confidence score from 0.0 to 1.0.
    """
    score = 0.0

    # Remove common stop words
    stop_words = {"the", "a", "an", "is", "are", "to", "for", "and", "or", "as", "in", "on", "at", "with"}

    # Title word overlap (up to 0.5)
    draft_words = set(draft_title.split()) - stop_words
    item_words = set(item_summary.split()) - stop_words
    if draft_words and item_words:
        overlap = len(draft_words & item_words)
        max_words = max(len(draft_words), len(item_words))
        score += (overlap / max_words) * 0.5

    # Problem/description overlap (up to 0.3)
    if draft_problem and item_description:
        draft_prob_words = set(draft_problem.split()) - stop_words
        item_desc_words = set(item_description.split()) - stop_words
        if draft_prob_words and item_desc_words:
            overlap = len(draft_prob_words & item_desc_words)
            max_words = max(len(draft_prob_words), len(item_desc_words))
            score += (overlap / max_words) * 0.3

    # Boost for exact title match
    if draft_title == item_summary:
        score = min(score + 0.3, 1.0)

    return score


async def _search_for_duplicates(
    draft: TicketDraft | None,
    channel_id: str | None = None,
) -> tuple[list[dict], list[float]]:
    """Search for duplicates - channel first, then Jira.

    Order:
    1. Check channel WorkItem registry (local truth)
    2. If no high-confidence match, check Jira (remote replica)

    This reflects the Git model: check local before remote.

    Returns tuple of:
    - list of {key, summary, url, status, assignee, updated, match_reason, source} dicts
    - list of confidence scores (0.0-1.0) for each duplicate

    For the best match (first), generates LLM explanation of why it matches.
    Fails gracefully - returns empty lists on any error.
    """
    if not draft or not draft.title:
        return [], []

    duplicates = []
    confidence_scores = []
    best_confidence = 0.0

    # 1. Search channel registry first (local)
    if channel_id:
        try:
            channel_duplicates = await _search_channel_registry(draft, channel_id)
            for dup in channel_duplicates:
                dup["source"] = "channel"  # Mark as local match
                duplicates.append(dup)
                conf = dup.get("confidence", 0)
                confidence_scores.append(conf)
                if conf > best_confidence:
                    best_confidence = conf

            if channel_duplicates:
                logger.info(
                    "Found channel registry matches",
                    extra={
                        "count": len(channel_duplicates),
                        "best_confidence": best_confidence,
                        "channel_id": channel_id,
                    },
                )
        except Exception as e:
            logger.warning(f"Channel registry search failed: {e}")

    # 2. If high confidence local match, skip Jira search
    if best_confidence >= 0.85:
        # Generate match explanation for best match
        if duplicates:
            match_reason = await _explain_duplicate_match(draft, duplicates[0])
            duplicates[0]["match_reason"] = match_reason
        return duplicates, confidence_scores

    # 3. Search Jira (remote)
    try:
        from src.config.settings import get_settings
        from src.jira.client import JiraService
        from src.skills.jira_search import search_similar_to_draft

        settings = get_settings()
        jira_service = JiraService(settings)

        try:
            result = await search_similar_to_draft(draft, jira_service, limit=5)

            # Track existing jira_keys from channel matches
            existing_keys = {d.get("jira_key") for d in duplicates if d.get("jira_key")}

            for issue in result.issues[:5]:
                # Skip if already in channel registry (avoid duplicates)
                if issue.key in existing_keys:
                    continue

                dup = {
                    "key": issue.key,
                    "summary": issue.summary,
                    "url": issue.url,
                    "status": issue.status,
                    "assignee": issue.assignee,
                    "updated": issue.updated,
                    "match_reason": "",
                    "source": "jira",  # Mark as remote match
                }

                # Compute confidence score
                confidence = _compute_confidence_score(draft, dup)
                duplicates.append(dup)
                confidence_scores.append(confidence)

        finally:
            await jira_service.close()

    except Exception as e:
        # Don't fail the workflow if Jira search fails
        logger.warning(
            "Failed to search Jira for duplicates",
            extra={"error": str(e)},
        )

    # Sort all results by confidence descending
    if duplicates:
        pairs = sorted(
            zip(duplicates, confidence_scores),
            key=lambda x: x[1],
            reverse=True
        )
        duplicates = [p[0] for p in pairs]
        confidence_scores = [p[1] for p in pairs]

        # Generate match explanation for best match only
        match_reason = await _explain_duplicate_match(draft, duplicates[0])
        duplicates[0]["match_reason"] = match_reason

        logger.info(
            "Found potential duplicates (channel-first)",
            extra={
                "count": len(duplicates),
                "draft_title": draft.title[:50],
                "best_match": duplicates[0].get("key"),
                "best_source": duplicates[0].get("source"),
                "best_confidence": confidence_scores[0] if confidence_scores else 0.0,
                "match_reason": match_reason,
            },
        )

    return duplicates, confidence_scores


async def decision_node(state: AgentState) -> dict[str, Any]:
    """Decide next action: ASK, PREVIEW, PREFLIGHT_REQUIRED, or READY_TO_CREATE.

    Logic:
    0. If thread already bound to a ticket -> PREVIEW (skip duplicate detection)
    1. If validation passed (is_valid=True) -> check duplicates
       - EXACT_MATCH (>85%): PREFLIGHT_REQUIRED (block until user chooses)
       - LIKELY_DUPLICATE (60-85%): PREVIEW with warning
       - NO_MATCH (<60%): PREVIEW normally
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
        # Ready for preview - check for duplicates first (channel-first)
        logger.info("Draft valid, checking for potential duplicates before preview (channel-first)")

        potential_duplicates, confidence_scores = await _search_for_duplicates(draft, channel_id)

        # Build preflight result
        preflight = PreflightResult.from_search_results(potential_duplicates, confidence_scores)

        # Decision based on preflight result
        if preflight.should_block_creation():
            # EXACT_MATCH: Block creation until user explicitly chooses
            logger.info(
                "EXACT_MATCH found, blocking creation",
                extra={
                    "best_match": preflight.best_match.key if preflight.best_match else None,
                    "confidence": preflight.best_match.confidence if preflight.best_match else 0,
                },
            )

            # Add confidence to duplicates for display
            for dup, conf in zip(potential_duplicates, confidence_scores):
                dup["confidence"] = conf

            return {
                "step_count": step_count + 1,
                "phase": AgentPhase.AWAITING_USER,
                "pending_questions": None,
                "decision_result": DecisionResult(
                    action="preflight_required",
                    reason=f"EXACT_MATCH found ({preflight.best_match.confidence*100:.0f}% confident). User must choose.",
                    potential_duplicates=potential_duplicates,
                    preflight_result=preflight.model_dump(),
                ).model_dump(),
            }

        # LIKELY_DUPLICATE or NO_MATCH: Proceed to preview
        dup_reason = "Draft meets minimum requirements"
        if preflight.should_warn():
            dup_reason = f"Draft meets requirements. Found {len(potential_duplicates)} likely duplicate(s) - please review."
        elif potential_duplicates:
            dup_reason = f"Draft meets requirements. Found {len(potential_duplicates)} potential match(es)."

        # Add confidence to duplicates for display
        for dup, conf in zip(potential_duplicates, confidence_scores):
            dup["confidence"] = conf

        return {
            "step_count": step_count + 1,
            "phase": AgentPhase.AWAITING_USER,
            "pending_questions": None,  # Clear any pending
            "decision_result": DecisionResult(
                action="preview",
                reason=dup_reason,
                potential_duplicates=potential_duplicates,
                preflight_result=preflight.model_dump() if potential_duplicates else None,
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


def get_decision_action(state: AgentState) -> Literal["ask", "preview", "ready", "preflight"]:
    """Get decision action from state for routing.

    Use in graph conditional edges.
    """
    result = state.get("decision_result", {})
    action = result.get("action", "ask")
    if action == "ready_to_create":
        return "ready"
    if action == "preflight_required":
        return "preflight"
    return action
