"""Extraction node - updates draft from conversation messages.

Patch-style: Only updates fields that have new information.
Adds evidence links for traceability.
Uses answer matcher for responses to pending questions.
"""
import json
import logging
import re
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
{conversation_context}
New message to process:
{message}

Extract any new information that should update the draft. Consider BOTH the conversation context above AND the new message. Return a JSON object with ONLY the fields that have new information. Do not repeat existing values.

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


GENERATION_PROMPT = '''You are helping build a Jira ticket. The user has asked you to propose content for specific fields.

Current draft:
{draft_json}

Context from the conversation:
{context}

Please generate content for these fields:
{fields_to_generate}

Return a JSON object with the generated content. For acceptance_criteria, provide a list of 3-5 testable criteria. For other fields, provide appropriate content based on the context.

JSON response:'''


EXTRACTION_PROMPT_WITH_REFERENCE = '''You are extracting requirements from a conversation to build a Jira ticket draft.

The user is referencing prior discussion in the thread. Here is the recent context:

{thread_context}
{review_artifact_context}
---

Current draft state:
{draft_json}

New message to process:
{message}

Extract information from the user's request, using the thread context and architecture review as reference material.
If the user says "create tickets for the architecture" or similar, extract multiple tickets from
the architecture review sections (components, risks, flows, etc.).

Fields you can update:
- title: Clear, concise ticket title
- problem: What problem we're solving
- proposed_solution: How we'll solve it
- acceptance_criteria: List of testable criteria (append new ones)
- constraints: List of {{"key", "value"}} technical decisions
- dependencies: List of external dependencies
- risks: List of potential risks

Return empty object {{}} if no new information to extract.

IMPORTANT: Only extract factual information stated in the message, thread context, or architecture review. Do not invent or assume.

JSON response:'''


def _detect_reference_to_prior_content(message: str) -> bool:
    """Check if user message references prior content in thread.

    Returns True if message contains patterns like:
    - "the architecture" / "this architecture"
    - "the review" / "this review" / "that analysis"
    - "from above" / "mentioned above"
    """
    message_lower = message.lower()

    reference_patterns = [
        r"\bthe\s+(?:architecture|review|analysis|design|proposal|approach)\b",
        r"\bthis\s+(?:architecture|review|analysis|design|proposal|approach)\b",
        r"\bthat\s+(?:architecture|review|analysis|design|proposal|approach)\b",
        r"\b(?:from|mentioned|discussed)\s+above\b",
        r"\bour\s+(?:discussion|conversation|review)\b",
    ]

    for pattern in reference_patterns:
        if re.search(pattern, message_lower):
            return True
    return False


async def _generate_content_for_fields(draft, fields: list[str], state: dict) -> None:
    """Generate content for fields when user asks us to propose.

    Modifies draft in-place with generated content.
    """
    if not fields:
        return

    llm = get_llm()
    draft_json = draft.model_dump_json(exclude={"evidence_links", "created_at", "updated_at"})

    # Build context from conversation and draft
    context_parts = []
    if draft.title:
        context_parts.append(f"Title: {draft.title}")
    if draft.problem:
        context_parts.append(f"Problem: {draft.problem}")
    if draft.proposed_solution:
        context_parts.append(f"Proposed solution: {draft.proposed_solution}")

    conversation_context = state.get("conversation_context", {})
    if conversation_context.get("summary"):
        context_parts.append(f"Conversation: {conversation_context['summary']}")

    context = "\n".join(context_parts) if context_parts else "No additional context"

    prompt = GENERATION_PROMPT.format(
        draft_json=draft_json,
        context=context,
        fields_to_generate="\n".join(f"- {f}" for f in fields),
    )

    try:
        response_text = await llm.chat(prompt)
        response_text = response_text.strip()

        # Parse JSON response
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        generated = json.loads(response_text) if response_text else {}

        if generated:
            logger.info(f"Generated content for fields: {list(generated.keys())}")
            # Patch draft with generated content
            for field, value in generated.items():
                # Skip constraints - they require special DraftConstraint format
                # that the LLM won't generate correctly
                if field == "constraints":
                    logger.debug("Skipping generated constraints - requires structured format")
                    continue
                # Skip open_questions - not a draft field
                if field == "open_questions":
                    logger.debug("Skipping open_questions - not a draft field")
                    continue
                if hasattr(draft, field):
                    if isinstance(value, list) and field in ["acceptance_criteria", "dependencies", "risks"]:
                        # Append to lists
                        existing = getattr(draft, field, [])
                        setattr(draft, field, existing + value)
                    else:
                        setattr(draft, field, value)

    except Exception as e:
        logger.warning(f"Failed to generate content: {e}")


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
    references_prior_content = _detect_reference_to_prior_content(message_text)
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
                await _generate_content_for_fields(draft, generate_fields, state)
                # Mark these as answered so we don't re-ask
                answer_match_result.unanswered_questions = [
                    q for q in answer_match_result.unanswered_questions
                    if q not in generate_fields
                ]
                answer_match_result.all_answered = len(answer_match_result.unanswered_questions) == 0

        except Exception as e:
            logger.warning(f"Answer matching failed, falling back to extraction: {e}")

    # Prepare prompt
    draft_json = draft.model_dump_json(exclude={"evidence_links", "created_at", "updated_at"})

    # Build conversation context string (Phase 11)
    conversation_context = state.get("conversation_context")

    # Check for review_artifact (frozen architecture review from decision_approval)
    review_artifact = state.get("review_artifact")

    # If user referenced prior content OR we have review_artifact, use special prompt
    if (references_prior_content or review_artifact) and (conversation_context or review_artifact):
        # Build thread context from bot's messages (likely reviews/analyses)
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

        thread_context = "\n\n".join(thread_context_parts) if thread_context_parts else "No prior content found"

        # Build review artifact context (CRITICAL: preserves architecture after approval)
        review_artifact_context = ""
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

        logger.info(
            "Using reference-aware extraction prompt",
            extra={
                "has_thread_context": bool(thread_context_parts),
                "context_messages": len(thread_context_parts),
                "has_review_artifact": bool(review_artifact),
            }
        )

        prompt = EXTRACTION_PROMPT_WITH_REFERENCE.format(
            thread_context=thread_context,
            review_artifact_context=review_artifact_context,
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

    # Handle empty draft - use contextual hints instead of static intro/nudge
    is_first_message = state.get("is_first_message", True)
    if draft.is_empty():
        # Use onboarding module for contextual hints
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
            state_update["decision_result"] = {
                "action": "intro",
                "message": get_intro_message(),
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
        logger.info(f"Draft empty, returning contextual hint: {hint_result.hint_type}")

    return state_update
