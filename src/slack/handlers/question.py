"""Slack handlers for question answers.

Phase 36: Question Engine - Conversation Driver

Processes button clicks and text replies for questions.
"""

import logging
from typing import Any, Callable

from slack_bolt import App

from src.db.connection import get_connection
from src.db.task_plan_store import TaskPlanStore
from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


def register_question_handlers(app: App) -> None:
    """Register question-related button handlers."""

    @app.action({"action_id": {"type": "regex", "pattern": "^question_.*"}})
    def handle_question_button(ack, body, client, action):
        """Handle question option button click."""
        ack()

        action_id = action.get("action_id", "")
        value = action.get("value", "")
        channel_id = body.get("channel", {}).get("id", "")
        thread_ts = body.get("message", {}).get("thread_ts") or body.get("message", {}).get("ts")
        user_id = body.get("user", {}).get("id", "")

        _run_async(
            _handle_question_button_async(
                client, action_id, value, channel_id, thread_ts, user_id
            )
        )

    @app.action({"action_id": {"type": "regex", "pattern": "^budget_(proceed|wait|cancel)_.*"}})
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
) -> None:
    """Handle question button click asynchronously."""
    try:
        # Parse value: "{plan_id}:{question_id}:{version}:{option_id}:{encoded_value}"
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

        # Process the button answer
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
        task_plan.increment_version()
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
        task_plan.increment_version()
        await store.update(task_plan)
