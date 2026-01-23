"""Extraction node - updates draft from conversation messages.

Patch-style: Only updates fields that have new information.
Adds evidence links for traceability.
Uses answer matcher for responses to pending questions.
"""
import json
import logging
import re
import uuid
from typing import Any
from langchain_core.messages import HumanMessage, AIMessage

from src.schemas.state import AgentState, AgentPhase
from src.schemas.draft import TicketDraft, DraftConstraint, ConstraintStatus
from src.schemas.attribution import MessageAttribution
from src.schemas.conflict import DraftConflict, ConflictType, ConflictSide
from src.llm import get_llm
from src.skills.answer_matcher import match_answers
from src.skills.input_classifier import (
    classify_input,
    InputClass,
    normalize_question_key,
)

logger = logging.getLogger(__name__)


CONTRADICTION_CHECK_PROMPT = '''Check if these two statements contradict each other.

Statement A (existing):
{existing}

Statement B (proposed):
{proposed}

Return JSON:
{{"contradicts": true/false, "explanation": "brief explanation"}}

Only return true if they are truly incompatible - they can't both be true at the same time.
Return false if they:
- Are about different things
- One adds detail to the other
- They describe different aspects
- One is a refinement of the other

JSON response:'''


async def detect_value_conflict(
    field_name: str,
    existing_value: str,
    proposed_value: str,
    existing_attribution: MessageAttribution,
    proposed_attribution: MessageAttribution,
) -> DraftConflict | None:
    """Detect if a proposed value conflicts with existing.

    Uses LLM to check semantic contradiction between values.
    Returns DraftConflict if contradiction detected, None otherwise.

    Args:
        field_name: Field being updated
        existing_value: Current value in draft
        proposed_value: New value being proposed
        existing_attribution: Who set the existing value
        proposed_attribution: Who is proposing the new value

    Returns:
        DraftConflict if contradiction found, None if compatible
    """
    # Don't flag conflict if same user is updating
    if existing_attribution.author_user_id == proposed_attribution.author_user_id:
        return None

    # Don't flag conflict for empty existing values
    if not existing_value or not existing_value.strip():
        return None

    # Check if values are semantically the same or compatible
    try:
        llm = get_llm()
        prompt = CONTRADICTION_CHECK_PROMPT.format(
            existing=existing_value,
            proposed=proposed_value,
        )
        response_text = await llm.chat(prompt)
        response_text = response_text.strip()

        # Parse JSON response
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        result = json.loads(response_text) if response_text else {}

        if not result.get("contradicts", False):
            logger.debug(
                f"No conflict detected for {field_name}",
                extra={"explanation": result.get("explanation", "")},
            )
            return None

        # Create conflict
        conflict = DraftConflict(
            conflict_type=ConflictType.VALUE_OVERRIDE,
            field_name=field_name,
            description=result.get("explanation", f"Conflicting values for {field_name}"),
            existing=ConflictSide(
                content=existing_value,
                attribution=existing_attribution,
                label="Keep original",
            ),
            proposed=ConflictSide(
                content=proposed_value,
                attribution=proposed_attribution,
                label="Use new",
            ),
        )

        logger.info(
            f"Conflict detected for {field_name}",
            extra={
                "conflict_id": conflict.conflict_id,
                "existing_author": existing_attribution.author_user_id,
                "proposed_author": proposed_attribution.author_user_id,
            },
        )

        return conflict

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse contradiction check response: {e}")
        return None
    except Exception as e:
        logger.warning(f"Contradiction check failed: {e}")
        return None


async def _store_and_signal_conflicts(
    channel_id: str,
    thread_ts: str,
    conflicts: list[DraftConflict],
) -> None:
    """Store detected conflicts in database.

    Called when extraction detects semantic conflicts between
    different users' contributions. Stores conflicts for
    later resolution via UI buttons.

    Args:
        channel_id: Slack channel ID
        thread_ts: Thread timestamp
        conflicts: List of DraftConflict objects to store
    """
    from src.db import get_connection
    from src.db.conflict_store import ConflictStore

    try:
        async with get_connection() as conn:
            store = ConflictStore(conn)
            await store.ensure_table()
            for conflict in conflicts:
                await store.create(channel_id, thread_ts, conflict)
                logger.info(
                    f"Stored conflict: {conflict.conflict_id}",
                    extra={
                        "field": conflict.field_name,
                        "type": conflict.conflict_type.value,
                    },
                )
    except Exception as e:
        logger.error(f"Failed to store conflicts: {e}")


EXTRACTION_PROMPT = '''You are extracting requirements from a conversation to build a Jira ticket draft.

Current draft state:
{draft_json}
{conversation_context}
New message to process:
{message}

Extract any new information that should update the draft. Consider BOTH the conversation context above AND the new message. Return a JSON object with ONLY the fields that have new information. Do not repeat existing values.

Fields you can update:
- title: Clear, concise ticket title (do NOT prefix with "Epic:", "Story:", etc.)
- problem: What problem we're solving
- proposed_solution: How we'll solve it
- acceptance_criteria: List of testable criteria (append new ones)
- constraints: List of {{"key", "value"}} technical decisions
- dependencies: List of external dependencies
- risks: List of potential risks
- issue_type: Type of work item (epic, story, task, bug)
  Only set if user explicitly mentions type: "create an epic", "make a story", "this is a bug"
- requested_scope: What to generate (epics_only, full_plan, single_item)
  - epics_only: User says "only epic(s)", "just epics", "epic-level only"
  - full_plan: User says "full breakdown", "complete plan", "with stories"
  - single_item: Default for normal requests

Return empty object {{}} if no new information to extract.

IMPORTANT: Only extract factual information stated in the message. Do not invent or assume.
IMPORTANT: Do NOT put "Epic:" or "Story:" prefixes in the title. Use issue_type field instead.

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
- title: Clear, concise ticket title (do NOT prefix with "Epic:", "Story:", etc.)
- problem: What problem we're solving
- proposed_solution: How we'll solve it
- acceptance_criteria: List of testable criteria (append new ones)
- constraints: List of {{"key", "value"}} technical decisions
- dependencies: List of external dependencies
- risks: List of potential risks
- issue_type: Type of work item (epic, story, task, bug)
  Only set if user explicitly mentions type: "create an epic", "make a story", "this is a bug"
- requested_scope: What to generate (epics_only, full_plan, single_item)
  - epics_only: User says "only epic(s)", "just epics", "epic-level only"
  - full_plan: User says "full breakdown", "complete plan", "with stories"
  - single_item: Default for normal requests

Return empty object {{}} if no new information to extract.

IMPORTANT: Only extract factual information stated in the message, thread context, or architecture review. Do not invent or assume.
IMPORTANT: Do NOT put "Epic:" or "Story:" prefixes in the title. Use issue_type field instead.

JSON response:'''


# Phase 1: Extract just item list (lightweight, avoids truncation)
MULTI_ITEM_LIST_PROMPT = '''Analyze this review and list ALL proposed work items.

Review text:
{review_text}

Topic: {topic}
Scope: {scope}

CRITICAL: Return ONLY a valid JSON array. No text before or after. No explanations.

Format (copy this structure exactly):
[
  {{"type": "epic", "title": "Short title here"}},
  {{"type": "story", "title": "Short title here", "parent_index": 0}}
]

Rules:
- "N epics" = N separate Epic items
- "epic with N stories" = 1 Epic at index 0, N Stories with parent_index: 0
- parent_index is the array index of the parent Epic (if any)
- Keep titles SHORT (under 80 chars)
- Do NOT include descriptions

IMPORTANT: Your response must start with [ and end with ]. Nothing else.
'''

# Phase 2: Get full details for a single item
SINGLE_ITEM_DETAIL_PROMPT = '''Generate Jira ticket content for this work item.

Topic: {topic}
Item type: {item_type}
Item title: {item_title}

Context from review:
{review_excerpt}

Return JSON with full details:
{{"title": "Clear concise title", "description": "Detailed description with context, acceptance criteria if story"}}

Keep the description focused and actionable (2-4 paragraphs max).
'''


async def extract_multi_items_from_review(review_text: str, scope: str, topic: str) -> list[dict]:
    """Extract multiple work items from review text using two-phase approach.

    Phase 1: Extract item list (type + title only) - small response, no truncation
    Phase 2: For each item, extract full description separately

    Returns list of items with:
    - id: UUID for internal tracking
    - type: "epic" or "story"
    - title: Item title
    - description: Item description
    - parent_id: For stories, references epic's item ID (not Jira key)

    Args:
        review_text: The review content to analyze
        scope: User-selected scope (decision, full, custom)
        topic: Topic of the review

    Returns:
        List of extracted items with UUIDs assigned
    """
    llm = get_llm()

    # Phase 1: Get item list (lightweight)
    list_prompt = MULTI_ITEM_LIST_PROMPT.format(
        review_text=review_text[:3000],
        topic=topic,
        scope=scope,
    )

    try:
        logger.info("Phase 1: Extracting item list from review")
        response_text = await llm.chat(list_prompt)
        logger.info(f"Phase 1 raw LLM response: {response_text[:500]}")
        item_list = _parse_json_response(response_text)

        if not isinstance(item_list, list):
            logger.warning(f"Expected list from item list extraction, got {type(item_list)}")
            return []

        if not item_list:
            logger.info("No items found in review")
            return []

        logger.info(f"Phase 1 complete: Found {len(item_list)} items")

        # Assign UUIDs and resolve parent relationships first
        items_with_ids = []
        for idx, item in enumerate(item_list):
            if not isinstance(item, dict):
                continue

            item_id = str(uuid.uuid4())
            item_type = item.get("type", "story").lower()
            if item_type not in ("epic", "story"):
                item_type = "story"

            items_with_ids.append({
                "id": item_id,
                "type": item_type,
                "title": item.get("title", "Untitled"),
                "description": "",  # Will be filled in Phase 2
                "parent_index": item.get("parent_index"),
            })

        # Resolve parent_index to parent_id
        for item in items_with_ids:
            parent_index = item.pop("parent_index", None)
            if parent_index is not None and isinstance(parent_index, int):
                if 0 <= parent_index < len(items_with_ids):
                    parent_item = items_with_ids[parent_index]
                    if parent_item["type"] == "epic":
                        item["parent_id"] = parent_item["id"]
                    else:
                        item["parent_id"] = None
                else:
                    item["parent_id"] = None
            else:
                item["parent_id"] = None

        # Phase 2: Get full details for each item (one at a time)
        logger.info(f"Phase 2: Extracting details for {len(items_with_ids)} items")
        review_excerpt = review_text[:2000]  # Context for detail extraction

        for i, item in enumerate(items_with_ids):
            try:
                detail_prompt = SINGLE_ITEM_DETAIL_PROMPT.format(
                    topic=topic,
                    item_type=item["type"],
                    item_title=item["title"],
                    review_excerpt=review_excerpt,
                )

                detail_response = await llm.chat(detail_prompt)
                logger.debug(f"Phase 2 raw LLM response for item {i}: {detail_response[:300]}")
                details = _parse_json_response(detail_response)

                if isinstance(details, dict):
                    # Update title if improved
                    if details.get("title"):
                        item["title"] = details["title"]
                    # Set description
                    item["description"] = details.get("description", "")

                logger.info(f"Phase 2: Extracted details for item {i+1}/{len(items_with_ids)}: {item['title'][:50]}")

            except Exception as e:
                logger.warning(f"Failed to extract details for item {i}: {e}")
                # Keep the item with empty description rather than failing entirely

        logger.info(
            "Extracted multi-items from review (two-phase)",
            extra={
                "item_count": len(items_with_ids),
                "epics": sum(1 for i in items_with_ids if i["type"] == "epic"),
                "stories": sum(1 for i in items_with_ids if i["type"] == "story"),
                "topic": topic,
            }
        )

        return items_with_ids

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse multi-item extraction response: {e}")
        return []
    except Exception as e:
        logger.error(f"Multi-item extraction failed: {e}")
        return []


def _parse_json_response(response_text: str) -> Any:
    """Parse JSON from LLM response, handling common issues."""
    response_text = response_text.strip()

    # Handle markdown code blocks
    if response_text.startswith("```"):
        parts = response_text.split("```")
        if len(parts) >= 2:
            response_text = parts[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

    if not response_text:
        return None

    # Log raw response for debugging
    logger.debug(f"Parsing JSON response: {response_text[:300]}...")

    # Try parsing as-is first
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # Fix common LLM JSON issues
    fixed = response_text

    # Remove trailing commas before ] or }
    fixed = re.sub(r',\s*]', ']', fixed)
    fixed = re.sub(r',\s*}', '}', fixed)

    # Handle concatenated JSON objects (no array brackets)
    # e.g., '{"a":1} {"b":2}' -> '[{"a":1}, {"b":2}]'
    if fixed.startswith("{") and not fixed.startswith("["):
        # Find all JSON objects by matching balanced braces
        objects = []
        depth = 0
        start = None
        in_string = False
        escape = False

        for i, char in enumerate(fixed):
            if escape:
                escape = False
                continue
            if char == '\\':
                escape = True
                continue
            if char == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue

            if char == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(fixed[start:i+1])
                    start = None

        if len(objects) > 1:
            # Multiple objects found - wrap in array
            fixed = '[' + ', '.join(objects) + ']'
            logger.info(f"Wrapped {len(objects)} concatenated JSON objects into array")

    # Try to extract JSON array or object if there's extra text
    array_match = re.search(r'\[[\s\S]*\]', fixed)
    if array_match:
        fixed = array_match.group(0)
    else:
        obj_match = re.search(r'\{[\s\S]*\}', fixed)
        if obj_match:
            fixed = obj_match.group(0)

    # Remove trailing commas again after extraction
    fixed = re.sub(r',\s*]', ']', fixed)
    fixed = re.sub(r',\s*}', '}', fixed)

    try:
        return json.loads(fixed)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed even after fixes: {e}")
        logger.warning(f"Original response: {response_text[:500]}")
        logger.warning(f"After fixes: {fixed[:500]}")
        raise


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

        # Handle case where LLM returns a list (multi-ticket request)
        if isinstance(generated, list):
            if generated:
                logger.info(f"LLM returned list of {len(generated)} items, using first item")
                generated = generated[0] if isinstance(generated[0], dict) else {}
            else:
                generated = {}

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
                await _store_and_signal_conflicts(
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
