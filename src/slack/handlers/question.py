"""Slack handlers for question answers.

Phase 36: Question Engine - Conversation Driver
Phase 45: Decision detection in review answers

Processes button clicks and text replies for questions.
"""

import logging
import re
from typing import Any, Callable

from slack_bolt import App

from src.db.connection import get_connection
from src.db.task_plan_store import TaskPlanStore
from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


async def _handle_record_decisions_async(
    client,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    team_id: str,
    message_ts: str,
) -> None:
    """Phase 45: Create formal Decision entities from captured decisions.

    Retrieves captured_decisions from review_context, creates Decision entities,
    posts canonical messages, and pins them.

    Args:
        client: Slack client
        channel_id: Slack channel ID
        thread_ts: Thread timestamp
        user_id: User who clicked the button
        team_id: Team ID for session lookup
        message_ts: Message timestamp to update
    """
    from src.slack.session import SessionIdentity
    from src.graph.runner import get_runner
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.schemas.decision import DecisionType
    from src.slack.blocks.decision_cards import build_compact_draft_card

    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )

    try:
        runner = get_runner(identity)
        state = await runner._get_current_state()
        review_context = state.get("review_context", {})
        captured_decisions = review_context.get("captured_decisions", [])

        if not captured_decisions:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                thread_ts=thread_ts,
                text="No decisions to record.",
            )
            return

        # Create Decision entities and post canonical messages
        created_decisions = []
        pinned_count = 0

        async with get_connection() as conn:
            store = DecisionStore(conn)

            for captured in captured_decisions:
                try:
                    decision_type = DecisionType(captured.get("decision_type", "arch"))
                except ValueError:
                    decision_type = DecisionType.ARCH

                decision = await store.create(
                    channel_id=channel_id,
                    decision_type=decision_type,
                    title=captured.get("decision_text", "Untitled decision")[:100],
                    description=captured.get("decision_text", ""),
                    created_by=user_id,
                    # Note: create() always creates in PROPOSED status
                )
                created_decisions.append(decision)

                # Post canonical message for this decision
                blocks = build_compact_draft_card(decision)
                try:
                    post_result = client.chat_postMessage(
                        channel=channel_id,
                        blocks=blocks,
                        text=f"Decision: {decision.title}",
                    )

                    canonical_ts = post_result.get("ts")
                    if canonical_ts:
                        # Store canonical message reference
                        await store.set_canonical_message(
                            decision_id=decision.id,
                            message_ts=canonical_ts,
                        )

                        # Pin the canonical message
                        try:
                            client.pins_add(
                                channel=channel_id,
                                timestamp=canonical_ts,
                            )
                            pinned_count += 1
                        except Exception as pin_error:
                            logger.warning(f"Could not pin decision message: {pin_error}")

                except Exception as post_error:
                    logger.error(f"Could not post canonical message: {post_error}")

                logger.info(
                    "Created and posted decision",
                    extra={
                        "decision_id": decision.id,
                        "decision_type": decision_type.value,
                        "title": decision.title[:50],
                    },
                )

        # Update the transition offer message
        decision_list = "\n".join(
            f"• *{d.title}* (_{d.decision_type.value.upper()}_)"
            for d in created_decisions
        )

        pin_status = f" ({pinned_count} pinned)" if pinned_count > 0 else ""

        try:
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text=f"Created {len(created_decisions)} decision(s)",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":white_check_mark: *Created {len(created_decisions)} decision(s){pin_status}:*\n\n{decision_list}",
                        },
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": "_Decisions are in PROPOSED status. Click to edit or approve._",
                            }
                        ],
                    },
                ],
            )
        except Exception as e:
            logger.warning(f"Could not update decision message: {e}")

        # Clear captured_decisions from review_context
        review_context["captured_decisions"] = []
        await runner._update_state({"review_context": review_context})

        # Post notification in thread
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":pushpin: Created {len(created_decisions)} decision(s) - see pinned messages in channel.",
        )

    except Exception as e:
        logger.error(f"Failed to record decisions: {e}")
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":warning: Failed to record decisions: {e}",
        )


async def _post_decision_transition_offer(
    client,
    channel_id: str,
    thread_ts: str,
    captured_decisions: list[dict],
) -> None:
    """Phase 45: Post transition offer when decisions have been captured.

    Shows a summary of captured decisions and offers to create formal
    Decision entities or continue the discussion.

    Args:
        client: Slack client
        channel_id: Slack channel ID
        thread_ts: Thread timestamp
        captured_decisions: List of captured decision dicts
    """
    if not captured_decisions:
        return

    # Build decision summary
    decision_bullets = []
    for d in captured_decisions[:5]:  # Limit to 5
        decision_type = d.get("decision_type", "").upper()
        decision_text = d.get("decision_text", "")
        decision_bullets.append(f"• *[{decision_type}]* {decision_text}")

    decisions_summary = "\n".join(decision_bullets)

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":memo: *Decisions captured during this discussion:*\n\n{decisions_summary}",
            },
        },
        {
            "type": "actions",
            "block_id": "decision_transition_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Record Decisions"},
                    "style": "primary",
                    "action_id": f"record_decisions_{thread_ts}",
                    "value": thread_ts,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Continue Discussion"},
                    "action_id": f"continue_discussion_{thread_ts}",
                    "value": thread_ts,
                },
            ],
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_Recording creates pinned Decision cards in the channel._",
                }
            ],
        },
    ]

    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=blocks,
            text=f"Captured {len(captured_decisions)} decision(s). Record them?",
        )
        logger.info(
            f"Posted decision transition offer",
            extra={
                "decisions_count": len(captured_decisions),
                "channel_id": channel_id,
                "thread_ts": thread_ts,
            },
        )
    except Exception as e:
        logger.error(f"Failed to post decision transition offer: {e}")


async def _detect_and_capture_decision(
    client,
    channel_id: str,
    thread_ts: str,
    answer_text: str,
    question_id: str,
    pending_questions: list[dict],
    review_context: dict,
) -> None:
    """Phase 45: Detect if answer contains a decision and capture it.

    Uses LLM-based DecisionDetector to analyze the answer for implicit decisions.
    If a decision is detected with high confidence, it's added to the
    captured_decisions list in review_context.

    Args:
        client: Slack client for posting acknowledgment
        channel_id: Slack channel ID
        thread_ts: Thread timestamp
        answer_text: The user's answer text
        question_id: ID of the question being answered
        pending_questions: List of question dicts
        review_context: Review context dict (modified in place)
    """
    from src.questions.decision_detector import detect_decision
    from src.schemas.question import QuestionTask, QuestionType

    try:
        # Build question context for decision detection
        question_context = None
        for q in pending_questions:
            if q.get("question_id") == question_id:
                question_context = QuestionTask(
                    question_id=q.get("question_id", ""),
                    question_type=QuestionType(q.get("question_type", "ask_user")),
                    question_text=q.get("question_text", ""),
                    target_field=q.get("target_field"),
                    options=None,  # Options not needed for detection
                )
                break

        # Detect decision using LLM
        decision = await detect_decision(answer_text, question_context)

        if decision and decision.confidence >= 0.7:
            # Store captured decision in review_context
            captured_decisions = review_context.get("captured_decisions", [])
            captured_decisions.append({
                "decision_text": decision.decision_text,
                "decision_type": decision.decision_type.value,
                "confidence": decision.confidence,
                "source_question": decision.source_question,
                "captured_at": decision.captured_at.isoformat(),
            })
            review_context["captured_decisions"] = captured_decisions

            # Post acknowledgment
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":white_check_mark: Noted decision: _{decision.decision_text}_",
            )

            logger.info(
                "Decision captured from review answer",
                extra={
                    "decision_text": decision.decision_text[:50],
                    "decision_type": decision.decision_type.value,
                    "confidence": decision.confidence,
                    "question_id": question_id,
                },
            )

    except Exception as e:
        # Decision detection is non-blocking - log and continue
        logger.warning(f"Decision detection failed (non-blocking): {e}")


def register_question_handlers(app: App) -> None:
    """Register question-related button handlers."""

    @app.action(re.compile(r"^(question|review_question)_.*"))
    def handle_question_button(ack, body, client, action):
        """Handle question option button click."""
        ack()

        action_id = action.get("action_id", "")
        value = action.get("value", "")
        channel_id = body.get("channel", {}).get("id", "")
        message_ts = body.get("message", {}).get("ts")  # Original message with buttons
        thread_ts = body.get("message", {}).get("thread_ts") or message_ts
        user_id = body.get("user", {}).get("id", "")
        # Extract team_id from body (critical for session lookup)
        team_id = body.get("team", {}).get("id") or body.get("user", {}).get("team_id", "")

        _run_async(
            _handle_question_button_async(
                client, action_id, value, channel_id, thread_ts, user_id, message_ts, team_id
            )
        )

    @app.action(re.compile(r"^budget_(proceed|wait|cancel)_.*"))
    def handle_budget_action(ack, body, client, action):
        """Handle budget exhausted action buttons."""
        ack()

        action_id = action.get("action_id", "")
        value = action.get("value", "")
        channel_id = body.get("channel", {}).get("id", "")
        thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
        user_id = body.get("user", {}).get("id", "")

        _run_async(
            _handle_budget_action_async(
                client, action_id, value, channel_id, thread_ts, user_id
            )
        )

    # Phase 45: Decision transition button handlers
    @app.action(re.compile(r"^record_decisions_.*"))
    def handle_record_decisions(ack, body, client, action):
        """Handle 'Record Decisions' button click."""
        ack()

        thread_ts = action.get("value", "")
        channel_id = body.get("channel", {}).get("id", "")
        user_id = body.get("user", {}).get("id", "")
        team_id = body.get("team", {}).get("id") or body.get("user", {}).get("team_id", "")
        message_ts = body.get("message", {}).get("ts")

        _run_async(
            _handle_record_decisions_async(
                client, channel_id, thread_ts, user_id, team_id, message_ts
            )
        )

    @app.action(re.compile(r"^continue_discussion_.*"))
    def handle_continue_discussion(ack, body, client, action):
        """Handle 'Continue Discussion' button click."""
        ack()

        thread_ts = action.get("value", "")
        channel_id = body.get("channel", {}).get("id", "")
        message_ts = body.get("message", {}).get("ts")

        # Just remove the transition offer buttons, don't create decisions
        try:
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text="Continuing discussion...",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": ":speech_balloon: Continuing discussion. Decisions noted but not yet recorded.",
                        }
                    }
                ],
            )
        except Exception as e:
            logger.warning(f"Could not update continue message: {e}")

    logger.info("Registered question button handlers")


async def _handle_question_button_async(
    client,
    action_id: str,
    value: str,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    message_ts: str = None,
    team_id: str = "",
) -> None:
    """Handle question button click asynchronously."""
    try:
        # Check for review question format first (Phase 37)
        # Format: "review_answer:{artifact_id}:{option_id}:{value}"
        if value.startswith("review_answer:"):
            parts = value.split(":", 3)
            if len(parts) >= 4:
                _, artifact_id, option_id, encoded_value = parts

                # Handle "Other" button for review
                if option_id == "other":
                    _handle_other_selected(client, channel_id, thread_ts, "review")
                    return

                await _handle_review_question_answer(
                    client,
                    channel_id,
                    thread_ts,
                    user_id,
                    artifact_id,  # question_id is artifact_id for reviews
                    option_id,
                    encoded_value,
                    message_ts,
                    team_id,
                )
                return

        # Parse TaskPlan question value: "{plan_id}:{question_id}:{version}:{option_id}:{encoded_value}"
        parts = value.split(":", 4)
        if len(parts) < 4:
            logger.error(f"Invalid question button value: {value}")
            return

        plan_id, question_id, version_str, rest = parts[0], parts[1], parts[2], ":".join(parts[3:])
        plan_version = int(version_str)
        option_id, encoded_value = rest.split(":", 1) if ":" in rest else (rest, rest)

        # Handle "Other" or "Reply" button
        if option_id in ("other", "reply"):
            _handle_other_selected(client, channel_id, thread_ts, question_id)
            return

        # Check if this is a review question (plan_id starts with "review_")
        if plan_id.startswith("review_"):
            # Handle review question answer without TaskPlan
            # Note: question_id is the actual question ID (e.g., "review_q_0")
            await _handle_review_question_answer(
                client,
                channel_id,
                thread_ts,
                user_id,
                question_id,  # Pass the actual question_id, not plan_id
                option_id,
                encoded_value,
                message_ts,
                team_id,
            )
            return

        # Process the button answer for TaskPlan
        result = await _process_button_answer(
            plan_id,
            question_id,
            plan_version,
            action_id,
            value,
            channel_id,
            thread_ts,
            user_id,
        )

        # Handle result
        decision = result.get("decision_result", {})
        if decision.get("action") == "stale_approval":
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="This question has already been answered or the plan has changed.",
            )
        elif decision.get("action") == "question_posted":
            # New question - post it
            from src.slack.blocks.question import build_question_blocks
            question_data = decision.get("question", {})
            blocks = build_question_blocks(
                question_data,
                decision.get("plan_id"),
                decision.get("plan_version"),
            )
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                blocks=blocks,
                text=question_data.get("question_text", "Next question"),
            )
        elif decision.get("action") == "task_plan_complete":
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="All questions answered. Proceeding...",
            )

    except Exception as e:
        logger.error(f"Question button handler error: {e}")
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Error processing answer: {e}",
        )


async def _handle_budget_action_async(
    client,
    action_id: str,
    value: str,
    channel_id: str,
    thread_ts: str,
    user_id: str,
) -> None:
    """Handle budget action button asynchronously."""
    try:
        plan_id, action_type = value.split(":", 1)

        if action_type == "proceed":
            await _resume_plan_with_gaps(plan_id, channel_id, thread_ts)
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Proceeding with available information...",
            )
        elif action_type == "wait":
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Waiting for more input. Reply when ready.",
            )
        elif action_type == "cancel":
            await _cancel_plan(plan_id)
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text="Operation canceled.",
            )

    except Exception as e:
        logger.error(f"Budget action handler error: {e}")


def _handle_other_selected(client, channel_id: str, thread_ts: str, question_id: str):
    """Handle 'Other' button selection."""
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text="Please type your answer in the thread.",
    )


async def _handle_review_question_answer(
    client,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    question_id: str,
    option_id: str,
    encoded_value: str,
    message_ts: str = None,
    team_id: str = "",
) -> None:
    """Handle review question button answer (Phase 37, fixed Phase 43).

    Flow:
    1. Record answer in review_context.answers (NO LLM call)
    2. If more questions remain, show next question
    3. Only when ALL questions answered, trigger LLM synthesis
    """
    from src.slack.session import SessionIdentity
    from src.graph.runner import get_runner
    from src.slack.blocks.question import build_question_blocks

    # Create identity for session lookup (team_id from Slack body)
    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )

    # Get runner and current state FIRST to look up the option label
    runner = get_runner(identity)
    state = await runner._get_current_state()
    review_context = state.get("review_context", {})

    # Find the display label from the question's options
    display_value = encoded_value  # fallback
    pending_questions = review_context.get("pending_questions", [])
    for q in pending_questions:
        if q.get("question_id") == question_id:
            options = q.get("options", []) or []
            for opt in options:
                if opt.get("option_id") == option_id or opt.get("value") == encoded_value:
                    display_value = opt.get("label", encoded_value)
                    break
            break

    if not review_context:
        logger.warning("No review_context found for question answer")
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Session expired. Please start a new review.",
        )
        return

    # Post confirmation as ephemeral message
    try:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            thread_ts=thread_ts,
            text=f"✓ Recorded: {display_value}",
        )
    except Exception as e:
        logger.warning(f"Could not post ephemeral confirmation: {e}")

    # Record the answer (NO LLM call here!)
    answers = review_context.get("answers", {})
    answers[question_id] = encoded_value
    review_context["answers"] = answers

    # Phase 45: Detect if answer contains a decision
    await _detect_and_capture_decision(
        client=client,
        channel_id=channel_id,
        thread_ts=thread_ts,
        answer_text=display_value,
        question_id=question_id,
        pending_questions=pending_questions,
        review_context=review_context,
    )

    # Find remaining unanswered questions
    pending_questions = review_context.get("pending_questions", [])
    unanswered = [
        q for q in pending_questions
        if q.get("question_id") not in answers
    ]

    logger.info(
        f"Review answer recorded: {question_id}={encoded_value}, "
        f"answered={len(answers)}, remaining={len(unanswered)}"
    )

    if unanswered:
        # More questions remain - just update state (questions already shown at once)
        # Don't post new questions - they're already visible in the thread
        await runner._update_state({"review_context": review_context})

        # Post progress update
        progress_text = f":white_check_mark: {len(answers)}/{len(pending_questions)} questions answered"
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=progress_text,
        )

        # Phase 45: Post transition offer if decisions have been captured
        # (don't wait until all questions answered)
        captured_decisions = review_context.get("captured_decisions", [])
        if captured_decisions:
            await _post_decision_transition_offer(
                client=client,
                channel_id=channel_id,
                thread_ts=thread_ts,
                captured_decisions=captured_decisions,
            )

    else:
        # All questions answered - trigger LLM synthesis
        await _trigger_review_synthesis(
            client, channel_id, thread_ts, user_id,
            runner, review_context, identity
        )


async def _trigger_review_synthesis(
    client,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    runner,
    review_context: dict,
    identity,
) -> None:
    """Trigger LLM synthesis after all questions are answered.

    This is the ONLY place where LLM is called for question flow.
    """
    from src.slack.progress import ProgressTracker
    from src.slack.handlers.dispatch import _dispatch_result

    tracker = ProgressTracker(client, channel_id, thread_ts)

    try:
        await tracker.start("Synthesizing answers...")

        # Format answers for LLM context
        answers = review_context.get("answers", {})
        pending_questions = review_context.get("pending_questions", [])

        # Build Q&A summary for synthesis
        qa_pairs = []
        for q in pending_questions:
            qid = q.get("question_id")
            question_text = q.get("question_text", "")
            answer_text = answers.get(qid, "Not answered")
            qa_pairs.append(f"Q: {question_text}\nA: {answer_text}")

        qa_summary = "\n\n".join(qa_pairs)

        # Update review_context with collected answers for synthesis
        review_context["qa_summary"] = qa_summary
        review_context["all_questions_answered"] = True
        await runner._update_state({"review_context": review_context})

        # Force REVIEW_CONTINUATION intent for synthesis
        from src.schemas.intent import Intent

        state = await runner._get_current_state()
        state["intent_result"] = {
            "intent": Intent.REVIEW_CONTINUATION.value,
            "confidence": 1.0,
            "reasons": ["all questions answered, triggering synthesis"],
        }
        await runner._update_state(state)

        # Run graph with synthesis trigger message
        result = await runner.run_with_message(
            message_text=f"[SYNTHESIS] User answered all questions:\n{qa_summary}",
            user_id=user_id,
        )

        # Dispatch result (will show buttons after synthesis)
        await _dispatch_result(result, identity, client, runner, tracker)

        # Phase 45: Check for captured decisions and offer transition
        # Get fresh state after synthesis (decisions may have been captured during continuation)
        updated_state = await runner._get_current_state()
        updated_review_context = updated_state.get("review_context", {})
        captured_decisions = updated_review_context.get("captured_decisions", [])

        if captured_decisions:
            await _post_decision_transition_offer(
                client=client,
                channel_id=channel_id,
                thread_ts=thread_ts,
                captured_decisions=captured_decisions,
            )

    except Exception as e:
        logger.error(f"Review synthesis error: {e}")
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Error synthesizing answers: {e}",
        )
    finally:
        await tracker.complete()


async def _process_button_answer(
    plan_id: str,
    question_id: str,
    plan_version: int,
    action_id: str,
    value: str,
    channel_id: str,
    thread_ts: str,
    user_id: str,
) -> dict:
    """Process button answer and return result."""
    # Deferred imports to avoid circular dependency
    from src.graph.nodes.question_executor import handle_question_answer
    from src.questions.answer_mapper import AnswerMapper

    async with get_connection() as conn:
        store = TaskPlanStore(conn)
        task_plan = await store.get(plan_id)

        if not task_plan:
            return {"decision_result": {"action": "plan_not_found"}}

        # Version check
        if task_plan.version != plan_version:
            return {"decision_result": {"action": "stale_approval"}}

        # Find task with this question
        task = None
        for t in task_plan.tasks:
            if t.is_question and t.question_task.question_id == question_id:
                task = t
                break

        if not task:
            return {"decision_result": {"action": "task_not_found"}}

        # Map button click to patch
        patch = AnswerMapper.map_button_click(action_id, value, task.question_task)

        # Handle answer
        state = {
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "task_plan": task_plan.model_dump(),
        }

        return await handle_question_answer(state, plan_id, task.task_id, patch)


async def _resume_plan_with_gaps(plan_id: str, channel_id: str, thread_ts: str) -> None:
    """Resume plan execution skipping remaining questions."""
    from src.schemas.task_plan import TaskStatus, TaskPlanStatus
    from src.schemas.question import QuestionStatus

    async with get_connection() as conn:
        store = TaskPlanStore(conn)
        task_plan = await store.get(plan_id)

        if not task_plan:
            return

        # Skip all pending question tasks
        for task in task_plan.tasks:
            if task.is_question and task.status == TaskStatus.BLOCKED:
                task.status = TaskStatus.DONE
                task.question_task.status = QuestionStatus.SKIPPED

        task_plan.status = TaskPlanStatus.PENDING
        await store.update(task_plan)


async def _cancel_plan(plan_id: str) -> None:
    """Cancel the entire TaskPlan."""
    from src.schemas.task_plan import TaskStatus, TaskPlanStatus

    async with get_connection() as conn:
        store = TaskPlanStore(conn)
        task_plan = await store.get(plan_id)

        if not task_plan:
            return

        for task in task_plan.tasks:
            if task.status not in (TaskStatus.DONE, TaskStatus.CANCELED):
                task.status = TaskStatus.CANCELED

        task_plan.status = TaskPlanStatus.CANCELED
        await store.update(task_plan)
