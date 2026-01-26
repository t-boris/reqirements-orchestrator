"""Slack handlers for question answers.

Phase 36: Question Engine - Conversation Driver

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

        # Handle "Other" button
        if option_id == "other":
            _handle_other_selected(client, channel_id, thread_ts, question_id)
            return

        # Check if this is a review question (plan_id starts with "review_")
        if plan_id.startswith("review_"):
            # Handle review question answer without TaskPlan
            await _handle_review_question_answer(
                client,
                channel_id,
                thread_ts,
                user_id,
                plan_id,  # Use plan_id as context identifier
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

    # Disable buttons in original message by updating it
    if message_ts:
        try:
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text=f"✓ Selected: *{encoded_value}*",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"✓ Selected: *{encoded_value}*",
                        },
                    }
                ],
            )
        except Exception as e:
            logger.warning(f"Could not update question message: {e}")

    # Get runner and current state
    runner = get_runner(identity)
    state = await runner._get_current_state()
    review_context = state.get("review_context", {})

    if not review_context:
        logger.warning("No review_context found for question answer")
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Session expired. Please start a new review.",
        )
        return

    # Record the answer (NO LLM call here!)
    answers = review_context.get("answers", {})
    answers[question_id] = encoded_value
    review_context["answers"] = answers

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
        # More questions remain - show next question (NO LLM)
        next_question = unanswered[0]
        review_plan_id = f"review_{thread_ts}"

        question_blocks = build_question_blocks(
            question_data=next_question,
            plan_id=review_plan_id,
            plan_version=1,
        )

        # Add progress indicator
        progress_text = f"_Question {len(answers) + 1} of {len(pending_questions)}_"
        question_blocks.insert(0, {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": progress_text}]
        })

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            blocks=question_blocks,
            text=next_question.get("question_text", "Next question"),
        )

        # Update state with new answers
        await runner._update_state({"review_context": review_context})

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
