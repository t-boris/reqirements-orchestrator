"""Extraction node - updates draft from conversation messages.

Patch-style: Only updates fields that have new information.
Adds evidence links for traceability.
Uses answer matcher for responses to pending questions.
"""
import json
import logging
from typing import Any
from langchain_core.messages import HumanMessage

from src.schemas.state import AgentState, AgentPhase
from src.schemas.draft import TicketDraft, DraftConstraint, ConstraintStatus
from src.schemas.attribution import MessageAttribution
from src.schemas.conflict import DraftConflict
from src.llm import get_llm
from src.skills.answer_matcher import match_answers
from src.skills.input_classifier import (
    classify_input,
    normalize_question_key,
)

from src.graph.nodes.extraction.draft import (
    format_channel_context,
    detect_reference_to_prior_content,
    generate_content_for_fields,
    EXTRACTION_PROMPT,
    EXTRACTION_PROMPT_WITH_REFERENCE,
)
from src.graph.nodes.extraction.conflict import (
    detect_value_conflict,
    store_and_signal_conflicts,
)

logger = logging.getLogger(__name__)


async def extraction_node(state: AgentState) -> dict[str, Any]:
    """Extract requirements from latest message and patch draft.

    - Injects channel context on new thread (Phase 8)
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

    # Inject channel context if not already present (Phase 8 - Global State)
    channel_context = state.get("channel_context")
    if channel_context is None and channel_id:
        try:
            from src.context.retriever import ChannelContextRetriever, RetrievalMode
            from src.db.connection import get_connection

            async with get_connection() as conn:
                retriever = ChannelContextRetriever(conn)
                team_id = state.get("team_id", "default")  # Get from session if available
                ctx_result = await retriever.get_context(
                    team_id=team_id,
                    channel_id=channel_id,
                    mode=RetrievalMode.COMPACT,
                )
                channel_context = ctx_result.to_dict()
                logger.debug(f"Injected channel context v{ctx_result.context_version}")
        except Exception as e:
            logger.warning(f"Failed to inject channel context: {e}")
            # Non-blocking - continue without context

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

    # Check if message references prior content (Bug #2 fix)
    references_prior_content = detect_reference_to_prior_content(message_text)
    if references_prior_content:
        logger.info(
            "User referenced prior content, will include thread context in extraction",
            extra={"message_preview": message_text[:100]}
        )

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

            # Handle [GENERATE] signals - user wants us to propose content
            generate_fields = []
            for match in answer_match_result.matches:
                if match.answer == "[GENERATE]":
                    generate_fields.append(match.question)
                    logger.info(f"User requested generation for: {match.question}")

            if generate_fields:
                # Generate content for requested fields
                await generate_content_for_fields(draft, generate_fields, state)
                # Mark these as answered so we don't re-ask
                answer_match_result.unanswered_questions = [
                    q for q in answer_match_result.unanswered_questions
                    if q not in generate_fields
                ]
                answer_match_result.all_answered = len(answer_match_result.unanswered_questions) == 0

            # Phase 28.5 (R10): Record answered questions to prevent re-asking
            if answer_match_result.matches and channel_id and thread_ts:
                try:
                    from src.db import get_connection
                    from src.db.answered_questions_store import AnsweredQuestionsStore

                    user_id = state.get("user_id", "")
                    async with get_connection() as conn:
                        store = AnsweredQuestionsStore(conn)
                        await store.ensure_table()
                        for match in answer_match_result.matches:
                            if match.confidence >= 0.7:
                                question_key = normalize_question_key(match.question)
                                await store.record_answer(
                                    channel_id=channel_id,
                                    thread_ts=thread_ts,
                                    question_key=question_key,
                                    original_question=match.question,
                                    answer=match.answer,
                                    user_id=user_id,
                                )
                except Exception as e:
                    # Non-blocking - continue even if recording fails
                    logger.warning(f"Failed to record answered questions: {e}")

        except Exception as e:
            logger.warning(f"Answer matching failed, falling back to extraction: {e}")

    # Phase 28.5 (R7): Classify user input type for routing
    input_classification = None
    pending_q_list = pending_questions.get("questions", []) if pending_questions else None
    try:
        classification = await classify_input(message_text, pending_q_list)
        if classification.confidence >= 0.6:
            input_classification = classification.model_dump()
            logger.info(
                "Input classification completed",
                extra={
                    "input_class": classification.input_class.value,
                    "confidence": classification.confidence,
                    "structural_action": classification.structural_action,
                },
            )
    except Exception as e:
        logger.warning(f"Input classification failed: {e}")

    # Prepare prompt
    draft_json = draft.model_dump_json(exclude={"evidence_links", "created_at", "updated_at"})

    # Build conversation context string (Phase 11)
    conversation_context = state.get("conversation_context")

    # Format channel context (decisions, artifacts) - ALWAYS include
    channel_context_str = format_channel_context(channel_context)
    # Debug: Log what we got (unbuffered for immediate visibility)
    if channel_context:
        decisions_count = len(channel_context.get("recent_decisions", []))
        artifacts_count = len(channel_context.get("recent_artifacts", []))
        print(f"[EXTRACTION] Channel context loaded: {decisions_count} decisions, {artifacts_count} artifacts", flush=True)
        if decisions_count > 0:
            print(f"[EXTRACTION] Decisions: {channel_context.get('recent_decisions', [])[:2]}", flush=True)
    else:
        print("[EXTRACTION] WARNING: Channel context is None - decisions won't be included", flush=True)

    if channel_context_str:
        print(f"[EXTRACTION] Channel context formatted: {len(channel_context_str)} chars", flush=True)
        print(f"[EXTRACTION] Context preview: {channel_context_str[:500]}", flush=True)

    # Check for review_artifact (frozen architecture review from decision_approval)
    review_artifact = state.get("review_artifact")

    # If user referenced prior content OR we have review_artifact, use special prompt
    if (references_prior_content or review_artifact) and (conversation_context or review_artifact or channel_id):
        # Fix C: Use Architecture Reference Resolver for proper content resolution
        thread_context = ""
        review_artifact_context = ""

        # First, check if we have a review_artifact in state (highest priority)
        if review_artifact:
            artifact_summary = review_artifact.get("updated_summary") or review_artifact.get("summary", "")
            if artifact_summary:
                artifact_topic = review_artifact.get("topic", "Architecture Review")
                artifact_kind = review_artifact.get("kind", "architecture")
                artifact_persona = review_artifact.get("persona", "")
                review_artifact_context = f"""
=== APPROVED {artifact_kind.upper()} REVIEW ===
Topic: {artifact_topic}
Reviewed by: {artifact_persona}

{artifact_summary}
=== END APPROVED REVIEW ===
"""
                logger.info(
                    "Injecting review_artifact into extraction context",
                    extra={
                        "artifact_kind": artifact_kind,
                        "artifact_topic": artifact_topic,
                        "content_hash": review_artifact.get("content_hash", ""),
                    }
                )

        # If no review_artifact, use reference resolver to find architecture content
        if not review_artifact_context and channel_id:
            try:
                from src.context.reference_resolver import get_reference_bundle_for_extraction
                from src.db.connection import get_connection

                async with get_connection() as conn:
                    bundle = await get_reference_bundle_for_extraction(
                        conn=conn,
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        conversation_context=conversation_context,
                    )

                if not bundle.is_empty():
                    review_artifact_context = bundle.to_context_string()
                    logger.info(
                        f"Reference resolver found content: source={bundle.source}, count={bundle.decision_count}",
                    )
                else:
                    logger.warning("Reference resolver found no architecture content")

            except Exception as e:
                logger.warning(f"Reference resolver failed: {e}")

        # Build thread context from conversation messages (fallback/supplementary)
        thread_context_parts = []
        if conversation_context:
            conv_messages = conversation_context.get("messages", [])
            for msg in conv_messages[-10:]:  # Last 10 messages
                role = msg.get("role", "")
                content = msg.get("text", "")

                # Include bot messages (likely reviews) and longer human messages
                if (role == "assistant" and len(content) > 100) or (role == "user" and len(content) > 50):
                    user = msg.get("user", "Assistant" if role == "assistant" else "User")
                    thread_context_parts.append(f"[{user}]: {content}")

        if thread_context_parts:
            thread_context = "\n\n".join(thread_context_parts)
        elif not review_artifact_context:
            # Only say "No prior content" if we also have no artifact context
            thread_context = "No prior content found in thread"

        logger.info(
            "Using reference-aware extraction prompt",
            extra={
                "has_thread_context": bool(thread_context_parts),
                "context_messages": len(thread_context_parts),
                "has_review_artifact": bool(review_artifact),
                "has_resolved_context": bool(review_artifact_context),
            }
        )

        prompt = EXTRACTION_PROMPT_WITH_REFERENCE.format(
            thread_context=thread_context,
            review_artifact_context=review_artifact_context,
            channel_context=channel_context_str,
            draft_json=draft_json,
            message=message_text,
        )
    else:
        # Standard extraction with conversation context
        context_str = ""
        if conversation_context:
            logger.info(
                "Including conversation context in extraction",
                extra={
                    "has_summary": bool(conversation_context.get("summary")),
                    "message_count": len(conversation_context.get("messages", [])),
                }
            )
            parts = []
            if conversation_context.get("summary"):
                parts.append(f"Conversation summary:\n{conversation_context['summary']}")
            if conversation_context.get("messages"):
                # Format recent messages
                msg_lines = []
                for msg in conversation_context["messages"]:
                    user = msg.get("user", "unknown")
                    text = msg.get("text", "")
                    if text:
                        msg_lines.append(f"[{user}]: {text}")
                if msg_lines:
                    parts.append(f"Recent messages:\n" + "\n".join(msg_lines[-10:]))  # Last 10
            if parts:
                context_str = "\nConversation context:\n" + "\n\n".join(parts) + "\n"

        prompt = EXTRACTION_PROMPT.format(
            channel_context=channel_context_str,
            draft_json=draft_json,
            conversation_context=context_str,
            message=message_text,
        )

    # Call LLM for extraction
    try:
        llm = get_llm()
        response_text = await llm.chat(prompt)
        response_text = response_text.strip()

        # Parse JSON response
        # Handle markdown code blocks
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        extracted = json.loads(response_text) if response_text and response_text != "{}" else {}

        # Handle case where LLM returns a list (multi-ticket request)
        if isinstance(extracted, list):
            if extracted:
                logger.info(f"LLM returned list of {len(extracted)} items, using first item")
                extracted = extracted[0] if isinstance(extracted[0], dict) else {}
            else:
                extracted = {}

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

            # Handle issue_type and requested_scope (Phase 26)
            if "issue_type" in extracted:
                from src.schemas.draft import IssueType
                issue_type_raw = extracted.pop("issue_type", None)
                if issue_type_raw:
                    issue_type_str = str(issue_type_raw).lower().strip()
                    try:
                        draft.issue_type = IssueType(issue_type_str)
                        logger.info(f"Extracted issue_type: {draft.issue_type}")
                    except ValueError:
                        logger.warning(f"Invalid issue_type: {issue_type_str}")

            if "requested_scope" in extracted:
                from src.schemas.draft import RequestedScope
                scope_raw = extracted.pop("requested_scope", None)
                if scope_raw:
                    scope_str = str(scope_raw).lower().strip()
                    try:
                        draft.requested_scope = RequestedScope(scope_str)
                        logger.info(f"Extracted requested_scope: {draft.requested_scope}")
                    except ValueError:
                        logger.warning(f"Invalid requested_scope: {scope_str}")

            # Clean up title - remove type prefixes (Phase 26)
            if "title" in extracted:
                title = extracted["title"]
                # Remove common type prefixes that LLM might still add
                for prefix in ["Epic:", "Story:", "Task:", "Bug:", "EPIC:", "STORY:", "TASK:", "BUG:"]:
                    if title.startswith(prefix):
                        extracted["title"] = title[len(prefix):].strip()
                        logger.debug(f"Stripped '{prefix}' prefix from title")
                        break

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

            # Get user_id from state for attribution (Phase 27.1)
            user_id = state.get("user_id", "")
            message_ts = getattr(latest_human, "id", "") or thread_ts

            # Conflict detection storage (Phase 27.3)
            detected_conflicts: list[DraftConflict] = []

            # Patch draft with attribution for attributable fields
            attributable_fields = ["title", "problem", "proposed_solution"]
            for field, value in extracted.items():
                if field in attributable_fields and value and user_id:
                    # Check for conflict before updating (Phase 27.3)
                    existing_value = getattr(draft, field, "")
                    existing_attribution = draft.get_attribution(field)

                    if existing_value and existing_attribution:
                        # Create proposed attribution for comparison
                        proposed_attribution = MessageAttribution(
                            author_user_id=user_id,
                            source_message_ts=message_ts,
                        )

                        # Check for semantic conflict
                        conflict = await detect_value_conflict(
                            field_name=field,
                            existing_value=existing_value,
                            proposed_value=value,
                            existing_attribution=existing_attribution,
                            proposed_attribution=proposed_attribution,
                        )

                        if conflict:
                            detected_conflicts.append(conflict)
                            # Don't update the field - wait for resolution
                            continue

                    # No conflict or no existing attribution - apply update
                    draft.set_with_attribution(
                        field=field,
                        value=value,
                        author_user_id=user_id,
                        source_message_ts=message_ts,
                    )
                elif field not in attributable_fields:
                    # Regular patch for other fields
                    if hasattr(draft, field) and value is not None:
                        setattr(draft, field, value)

            # Increment version and timestamp after all updates
            from datetime import datetime
            draft.updated_at = datetime.utcnow()
            draft.version += 1

            # Add evidence links for all extracted fields
            for field in extracted.keys():
                draft.add_evidence(
                    message_ts=message_ts,
                    thread_ts=thread_ts,
                    channel_id=channel_id,
                    field_updated=field,
                    text_preview=message_text[:100],
                )

            # Log attribution tracking
            if user_id:
                logger.debug(
                    "Attribution tracked for extraction",
                    extra={
                        "user_id": user_id,
                        "fields_attributed": [f for f in extracted.keys() if f in attributable_fields],
                        "source_message_ts": message_ts,
                    }
                )

            # Handle detected conflicts (Phase 27.3)
            if detected_conflicts:
                await store_and_signal_conflicts(
                    channel_id=channel_id,
                    thread_ts=thread_ts,
                    conflicts=detected_conflicts,
                )
                # Signal that conflicts need resolution
                # The dispatcher will post conflict UI and block progress
                return {
                    "draft": draft,
                    "step_count": step_count + 1,
                    "phase": AgentPhase.COLLECTING,
                    "decision_result": {
                        "action": "conflict",
                        "conflicts": [c.model_dump() for c in detected_conflicts],
                    },
                }
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

    # Include channel context if newly fetched
    if channel_context is not None and state.get("channel_context") is None:
        state_update["channel_context"] = channel_context

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

    # Phase 28.5 (R7): Include input classification for decision routing
    if input_classification:
        state_update["input_classification"] = input_classification

    # Handle empty draft - behavior depends on intent
    is_first_message = state.get("is_first_message", True)
    if draft.is_empty():
        # Fix A: Check intent before deciding action
        intent_result = state.get("intent_result", {})
        current_intent = intent_result.get("intent", "").upper()

        # Intents that imply user has a real request (not just chatting)
        actionable_intents = {
            "WORKITEM_CREATE", "DRAFT_REFINE", "DRAFT_TRANSFORM",
            "REVIEW", "DECISION", "TICKET_ACTION", "JIRA_COMMAND",
            "JIRA_SEARCH", "CHANGE_REQUEST", "SYNC_REQUEST",
        }

        if current_intent in actionable_intents:
            # Fix B: User has a real request but we lack content
            # Don't show intro - ask for source instead
            logger.info(
                f"Draft empty but intent={current_intent}, asking for source",
                extra={"intent": current_intent, "requested_scope": str(draft.requested_scope)},
            )

            # Build ask_scope_source response
            state_update["decision_result"] = {
                "action": "ask_scope_source",
                "message": (
                    "I can help create work items, but I need a source for the requirements.\n\n"
                    "Where should I look for the architecture/requirements?"
                ),
                "buttons": [
                    {"id": "scope_decisions", "label": "Use decisions in this thread", "value": "thread_decisions"},
                    {"id": "scope_pinned", "label": "Use pinned baseline", "value": "pinned_baseline"},
                    {"id": "scope_channel", "label": "Use channel context", "value": "channel_context"},
                    {"id": "scope_describe", "label": "Let me describe it", "value": "describe"},
                ],
            }
            state_update["is_first_message"] = False
            return state_update

        # For DISCUSSION/CONFUSED or unknown intents, use onboarding flow
        from src.slack.onboarding import classify_hesitation, HintType, get_intro_message

        # Get the user's message for classification
        user_message = ""
        if messages:
            last_human = [m for m in messages if isinstance(m, HumanMessage)]
            if last_human:
                user_message = last_human[-1].content if isinstance(last_human[-1].content, str) else str(last_human[-1].content)

        # Classify and get appropriate hint
        hint_result = await classify_hesitation(user_message, is_first_message)

        if hint_result.hint_type == HintType.NONE and is_first_message:
            # No specific hint detected on first message, use intro
            # But only if intent is truly conversational
            if current_intent in {"DISCUSSION", "META", "AMBIGUOUS", ""}:
                state_update["decision_result"] = {
                    "action": "intro",
                    "message": get_intro_message(),
                }
            else:
                # Unknown actionable intent - ask for clarification
                state_update["decision_result"] = {
                    "action": "nudge",
                    "message": (
                        "I'm not sure what you'd like to create.\n"
                        "Could you describe the feature, bug, or change?"
                    ),
                }
        elif hint_result.hint_type == HintType.NONE:
            # No hint needed, use standard nudge
            state_update["decision_result"] = {
                "action": "nudge",
                "message": (
                    "I didn't catch any concrete requirements yet.\n"
                    "Can you describe the feature, bug, or change you'd like to work on?"
                ),
            }
        else:
            # Return contextual hint
            state_update["decision_result"] = {
                "action": "hint",
                "message": hint_result.hint_message,
                "show_buttons": hint_result.show_buttons,
                "buttons": [b.copy() if isinstance(b, dict) else b for b in hint_result.buttons],
            }

        # Mark first message as done
        state_update["is_first_message"] = False
        logger.info(f"Draft empty, intent={current_intent}, hint={hint_result.hint_type}")

    return state_update
