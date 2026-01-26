"""Decision node - routes to ASK, PREVIEW, PREFLIGHT_REQUIRED, or READY_TO_CREATE.

Prioritizes most impactful issues first.
Smart batching: immediate if urgent, else batch related questions.
Re-ask logic: max 2 re-asks before proceeding with partial info.
Duplicate detection: searches for similar tickets before preview.
Preflight: blocks creation on EXACT_MATCH (>85% confidence) until user chooses.

EXECUTE is deferred to Phase 7 - only sets state to READY_TO_CREATE.
"""
import logging
from typing import Any, Literal

from src.schemas.state import AgentState, AgentPhase
from src.schemas.preflight import PreflightResult

from src.graph.nodes.decision.models import DecisionResult
from src.graph.nodes.decision.questions import prioritize_issues, batch_questions
from src.graph.nodes.decision.duplicates import search_for_duplicates
from src.graph.nodes.decision.refinement import build_refinement_prompt

logger = logging.getLogger(__name__)

# Max re-ask attempts before proceeding with partial info
MAX_REASK_COUNT = 2


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

    # Phase 28.5 (R7): Check for CHOICE input classification - route to transform
    input_classification = state.get("input_classification")
    if input_classification and input_classification.get("input_class") == "choice":
        structural_action = input_classification.get("structural_action")
        if structural_action:
            logger.info(
                "CHOICE input detected - should route to transform",
                extra={
                    "structural_action": structural_action,
                    "confidence": input_classification.get("confidence"),
                },
            )
            # Signal that a structural choice was made - handler should route to transform
            return {
                "step_count": step_count + 1,
                "phase": AgentPhase.AWAITING_USER,
                "decision_result": DecisionResult(
                    action="preview",  # Preview with transform hint
                    reason=f"User made structural choice: {structural_action}",
                ).model_dump(),
                "pending_action": {
                    "type": "transform",
                    "action": structural_action,
                    "from_input_classification": True,
                },
            }

    # Check for DRAFT_REFINE intent (Phase 26)
    # If user is asking meta-questions about the draft, generate clarifying response
    intent_result = state.get("intent_result", {})
    current_intent = intent_result.get("intent", "").upper()

    if current_intent == "DRAFT_REFINE" and draft and draft.title:
        # User is asking about the draft structure, not requesting review
        logger.info(
            "DRAFT_REFINE detected - generating clarification response",
            extra={
                "draft_title": draft.title[:50],
                "draft_issue_type": draft.issue_type.value if draft.issue_type else None,
            },
        )

        # Build a context-aware prompt for the refinement question
        refinement_prompt = build_refinement_prompt(draft, state)

        return {
            "step_count": step_count + 1,
            "phase": AgentPhase.AWAITING_USER,
            "decision_result": DecisionResult(
                action="draft_refine",
                reason="User asking about draft structure",
                refinement_prompt=refinement_prompt,
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

        potential_duplicates, confidence_scores = await search_for_duplicates(draft, channel_id)

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

    # Phase 28.4: Extract lifecycle and issue_type for lifecycle-aware questions
    structured_draft = state.get("structured_draft")
    lifecycle = None
    issue_type = None

    if structured_draft:
        lifecycle = structured_draft.lifecycle
        primary_item = structured_draft.get_primary_item()
        if primary_item:
            issue_type = primary_item.issue_type
    elif draft and hasattr(draft, "issue_type"):
        issue_type = draft.issue_type

    # Need to ask questions - with lifecycle-aware filtering (R5)
    questions = prioritize_issues(
        missing_fields,
        conflicts,
        suggestions,
        lifecycle=lifecycle,
        issue_type=issue_type,
    )

    # Phase 28.5 (R10): Filter out already-answered questions
    if questions and channel_id and thread_ts:
        try:
            from src.db import get_connection
            from src.db.answered_questions_store import AnsweredQuestionsStore
            from src.skills.input_classifier import normalize_question_key

            async with get_connection() as conn:
                store = AnsweredQuestionsStore(conn)
                await store.ensure_table()

                # Get question keys for the questions we're about to ask
                question_keys = [normalize_question_key(q) for q in questions]
                unanswered_keys = await store.filter_unanswered(
                    channel_id, thread_ts, question_keys
                )

                # Filter questions to only those not yet answered
                original_count = len(questions)
                questions = [
                    q for q in questions
                    if normalize_question_key(q) in unanswered_keys
                ]

                if len(questions) < original_count:
                    logger.info(
                        "Skipping already-answered questions",
                        extra={
                            "original_count": original_count,
                            "filtered_count": len(questions),
                            "skipped": original_count - len(questions),
                            "thread_ts": thread_ts,
                        },
                    )
        except Exception as e:
            # Non-blocking - continue with all questions if filtering fails
            logger.warning(f"Failed to filter answered questions: {e}")

    # If all questions were already answered, go to preview
    if not questions:
        logger.info(
            "All questions already answered - proceeding to preview",
            extra={"thread_ts": thread_ts},
        )
        return {
            "step_count": step_count + 1,
            "phase": AgentPhase.AWAITING_USER,
            "pending_questions": None,
            "decision_result": DecisionResult(
                action="preview",
                reason="All questions already answered - ready for review",
            ).model_dump(),
        }

    batched = batch_questions(questions)

    logger.info(
        "Asking user for more information",
        extra={
            "total_issues": len(questions),
            "batch_size": len(batched),
            "lifecycle": lifecycle.value if lifecycle else None,
            "issue_type": issue_type.value if issue_type else None,
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


def get_decision_action(state: AgentState) -> Literal["ask", "preview", "ready", "preflight", "draft_refine"]:
    """Get decision action from state for routing.

    Use in graph conditional edges.
    """
    result = state.get("decision_result", {})
    action = result.get("action", "ask")
    if action == "ready_to_create":
        return "ready"
    if action == "preflight_required":
        return "preflight"
    if action == "draft_refine":
        return "draft_refine"
    return action
