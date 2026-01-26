"""Core dispatch module - main router and shared utilities.

INVARIANT I1: SuperMode = sole UI contract
All user-facing messages use super_mode, never intent.
Intent is internal routing detail only.

Handles dispatching graph results to appropriate skills and extracting
content for ticket updates and comments.

Phase 29.4: Preflight Sync integration.
- Check for conflicts before ticket updates and transitions
- Show preflight UI when conflicts detected
- Handle user choices via button handlers
"""

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from slack_sdk.web import WebClient

from src.slack.session import SessionIdentity
from src.graph.runner import get_runner

if TYPE_CHECKING:
    from src.slack.progress import ProgressTracker
    from src.sync.preflight import PreflightResult
    from src.graph.state import AgentState
    from src.schemas.intent import SuperMode

# Phase 35: TaskPlan handlers (imported from task_plan.py)
from src.slack.handlers.dispatch.task_plan import (
    _handle_task_plan_created,
    _handle_task_confirmation,
    _handle_task_plan_complete,
    _handle_task_plan_blocked,
    _handle_task_failed,
    _handle_task_rejected,
)

# Phase 36: Question Engine handlers (imported from question.py)
from src.slack.handlers.dispatch.question import (
    _handle_question_posted,
    _handle_budget_exhausted,
    _post_question_ui,
    _post_budget_exhausted_ui,
)

# Jira operations handlers (imported from jira_ops.py)
from src.slack.handlers.dispatch.jira_ops import (
    _check_preflight_for_action,
    _extract_update_content,
    _extract_comment_content,
    _handle_ticket_action,
    _handle_create_stories,
    _handle_sync_request,
    _handle_jira_search,
    _handle_change_request_preview,
    _handle_ops_response,
    UPDATE_EXTRACTION_PROMPT,
    COMMENT_EXTRACTION_PROMPT,
    STORY_GENERATION_PROMPT,
)

# Review handlers (imported from review.py)
from src.slack.handlers.dispatch.review import (
    _handle_review_continuation,
    _handle_review,
)

logger = logging.getLogger(__name__)


async def resolve_attachment_context(
    state: "AgentState",
    mode: "SuperMode",
) -> "AgentState":
    """Resolve attachment context based on mode policy.

    Called after intent classification to populate attachment_context
    in state before graph nodes process the request.

    Intent-scoped rules:
    - CHAT: Don't include, offer available attachments
    - THINK: Pinned auto + top-K chunks if retrieval high
    - BUILD: Pinned auto + structural (requirements, AC)
    - OPERATE: Only logs, JSON, stacktraces via retrieval
    - DECIDE: Pinned + cited chunks with source refs

    Args:
        state: Current AgentState with channel_id and thread_ts.
        mode: SuperMode determining attachment policy.

    Returns:
        Updated AgentState with attachment_context populated.
    """
    from src.documents.retriever import AttachmentRetriever

    channel_id = state.get("channel_id")
    thread_ts = state.get("thread_ts")
    message = state.get("user_message", "")

    if not channel_id:
        return state

    try:
        retriever = AttachmentRetriever()
        context = await retriever.get_context(
            channel_id=channel_id,
            thread_ts=thread_ts,
            mode=mode,
            query=message,
        )

        state["attachment_context"] = context

        logger.debug(
            "Resolved attachment context",
            extra={
                "channel_id": channel_id,
                "thread_ts": thread_ts,
                "mode": mode.value,
                "pinned_count": len(context.pinned),
                "retrieved_count": len(context.retrieved_chunks),
                "available_count": len(context.offer_available),
                "total_tokens": context.total_tokens,
            }
        )

    except Exception as e:
        logger.warning(f"Failed to resolve attachment context: {e}")
        # Non-blocking - continue without attachment context

    return state


async def _dispatch_result(
    result: dict,
    identity: SessionIdentity,
    client: WebClient,
    runner,
    tracker: "ProgressTracker | None" = None,
):
    """Dispatch graph result to appropriate skill via dispatcher.

    Clean separation:
    - Runner: manages graph execution, returns DecisionResult
    - Dispatcher: calls appropriate skill based on decision
    - Handler: orchestrates and handles Slack-specific response

    Args:
        result: Graph result dict with action and data
        identity: Session identity
        client: Slack WebClient
        runner: Graph runner instance
        tracker: Optional ProgressTracker for status updates
    """
    from src.skills.dispatcher import SkillDispatcher
    from src.graph.nodes.decision import DecisionResult

    # Import domain-specific handlers
    from src.slack.handlers.dispatch.draft import (
        _handle_draft_conflict,
        _handle_transform_applied,
    )
    from src.slack.handlers.dispatch.decision import (
        _handle_decision_approval,
    )

    action = result.get("action", "continue")
    logger.info(f"_dispatch_result received action={action}, result_keys={list(result.keys())}")

    if action == "intro" or action == "nudge" or action == "hint":
        # Empty draft - send contextual hint message
        message = result.get("message", "Tell me what you'd like to work on.")
        show_buttons = result.get("show_buttons", False)
        buttons = result.get("buttons", [])

        if show_buttons and buttons:
            # Build message with buttons
            from src.slack.blocks import build_hint_with_buttons
            blocks = build_hint_with_buttons(message, buttons)
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text=message,
                blocks=blocks,
            )
        else:
            # Simple text message
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                text=message,
            )

    elif action == "ask_scope_source":
        # User has actionable intent but draft is empty - ask where to get content
        message = result.get("message", "Where should I look for requirements?")
        buttons = result.get("buttons", [])

        # Build scope source buttons
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message},
            },
        ]

        if buttons:
            button_elements = []
            for btn in buttons:
                button_elements.append({
                    "type": "button",
                    "text": {"type": "plain_text", "text": btn.get("label", btn.get("id", "Option"))},
                    "action_id": f"scope_source_{btn.get('id', 'unknown')}",
                    "value": btn.get("value", btn.get("id", "")),
                })

            blocks.append({
                "type": "actions",
                "block_id": "scope_source_buttons",
                "elements": button_elements,
            })

        resp = client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=message,
            blocks=blocks,
        )

        # Track this as actionable message
        if resp.get("ok") and resp.get("ts"):
            clear_old_actionable_and_track_new(
                client, identity.channel_id, identity.thread_ts, resp["ts"]
            )

    elif action == "ask":
        # Build DecisionResult from runner result
        decision = DecisionResult(
            action="ask",
            questions=result.get("questions", []),
            reason=result.get("reason", ""),
            is_reask=result.get("pending_questions", {}).get("re_ask_count", 0) > 0 if result.get("pending_questions") else False,
            reask_count=result.get("pending_questions", {}).get("re_ask_count", 0) if result.get("pending_questions") else 0,
        )

        # Get state_version and ui_version from runner for state-bound approvals (Phase 27.4)
        state = await runner._get_current_state()
        state_version = state.get("state_version", 0)
        ui_version = state.get("ui_version", 0)

        dispatcher = SkillDispatcher(client, identity, tracker)
        skill_result = await dispatcher.dispatch(
            decision, result.get("draft"), state_version=state_version, ui_version=ui_version
        )

        # Store pending questions in runner state
        if skill_result.get("success") and skill_result.get("pending_questions"):
            await runner.store_pending_questions(skill_result["pending_questions"])

    elif action == "preview":
        draft = result.get("draft")
        if draft:
            decision = DecisionResult(
                action="preview",
                reason=result.get("reason", ""),
                potential_duplicates=result.get("potential_duplicates", []),
            )

            # Get state_version and ui_version from runner for state-bound approvals (Phase 27.4)
            state = await runner._get_current_state()
            state_version = state.get("state_version", 0)
            ui_version = state.get("ui_version", 0)

            dispatcher = SkillDispatcher(client, identity, tracker)
            await dispatcher.dispatch(decision, draft, state_version=state_version, ui_version=ui_version)

    elif action == "ready":
        # Approved - notify user
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="Ticket approved and ready to create in Jira!",
        )

    elif action == "discussion":
        # Discussion response - single reply, no thread creation
        # Key: Discussion should respond WHERE the user mentioned us
        # No state updates, no progress tracker, just respond and stop
        discussion_msg = result.get("message", "")
        if discussion_msg:
            # Post directly to channel/thread where mentioned (no new thread)
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts if identity.thread_ts else None,
                text=discussion_msg,
            )

    elif action == "ops":
        # OPS response - debug or explain (Phase 25.2)
        await _handle_ops_response(result, identity, client)

    elif action == "draft_refine":
        # DRAFT_REFINE - user asking about draft structure (Phase 26)
        decision_result = result.get("decision_result", {})
        refinement_prompt = decision_result.get("refinement_prompt", "")

        if refinement_prompt:
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": refinement_prompt,
                    },
                }
            ]
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                blocks=blocks,
                text=refinement_prompt[:200],  # Fallback for notifications
            )
            logger.info(
                "Posted draft refinement response",
                extra={
                    "session_id": identity.session_id,
                    "prompt_length": len(refinement_prompt),
                },
            )
        else:
            # Fallback if no refinement prompt generated
            fallback_text = "I understand you're asking about the draft structure. Could you be more specific about what you'd like to adjust?"
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": fallback_text,
                    },
                }
            ]
            client.chat_postMessage(
                channel=identity.channel_id,
                thread_ts=identity.thread_ts,
                blocks=blocks,
                text=fallback_text,
            )

    elif action == "review_continuation":
        # Review continuation - synthesized response to user's answers
        await _handle_review_continuation(result, identity, client)

    elif action == "review":
        # Review response - persona-based analysis without Jira operations
        await _handle_review(result, identity, client)

    elif action == "jira_command_confirm":
        # Handle Jira command confirmation (Phase 21)
        from src.slack.handlers.jira_commands import handle_jira_command_confirm
        await handle_jira_command_confirm(result, identity, client)

    elif action == "jira_command_ambiguous":
        # Handle ambiguous Jira command target (Phase 21)
        from src.slack.handlers.jira_commands import handle_jira_command_ambiguous
        await handle_jira_command_ambiguous(result, identity, client)

    elif action == "ticket_action":
        # Handle operations on existing tickets (Phase 13.1)
        await _handle_ticket_action(result, identity, client)

    elif action == "decision_approval":
        # Architecture decision approval (Phase 14)
        await _handle_decision_approval(result, identity, client)

    elif action == "scope_gate":
        # AMBIGUOUS intent - show 3-button scope gate (Phase 20)
        from src.slack.blocks.scope_gate import build_scope_gate_blocks

        message_preview = result.get("message_preview", "")[:100]
        blocks = build_scope_gate_blocks(message_preview)

        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="How would you like me to help?",
            blocks=blocks,
        )

    elif action == "sync_request":
        # Sync request - trigger Jira sync analysis (Phase 21-04)
        await _handle_sync_request(result, identity, client)

    elif action == "jira_search":
        # Jira search - search for existing issues
        await _handle_jira_search(result, identity, client)

    elif action == "change_request_preview":
        # Change request - diff-based updates (Phase 25.3)
        await _handle_change_request_preview(client, identity.channel_id, identity.thread_ts, result)

    elif action == "change_request_error":
        # Change request error
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f":warning: {result.get('error', 'Unknown error')}",
        )

    elif action == "transform_applied":
        # DRAFT_TRANSFORM completed - show new structure (Phase 28.6, R8)
        await _handle_transform_applied(result, identity, client)

    elif action == "conflict":
        # Draft conflict detected - post conflict UI (Phase 27.3)
        await _handle_draft_conflict(result, identity, client)

    # Phase 35: TaskPlan action handlers
    elif action == "task_plan_created":
        await _handle_task_plan_created(client, result, identity)

    elif action == "task_confirmation_required":
        await _handle_task_confirmation(client, result, identity)

    elif action == "task_plan_complete":
        await _handle_task_plan_complete(client, result, identity)

    elif action == "task_plan_blocked":
        await _handle_task_plan_blocked(client, result, identity)

    elif action == "task_failed":
        await _handle_task_failed(client, result, identity)

    elif action == "task_rejected":
        await _handle_task_rejected(client, result, identity)

    # Phase 36: Question Engine action handlers
    elif action == "question_posted":
        await _handle_question_posted(client, result, identity)

    elif action == "budget_exhausted":
        await _handle_budget_exhausted(client, result, identity)

    elif action == "error":
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text=f"Sorry, I encountered an error: {result.get('error', 'Unknown error')}",
        )

    else:
        # Continue - acknowledge receipt
        client.chat_postMessage(
            channel=identity.channel_id,
            thread_ts=identity.thread_ts,
            text="Got it! I'm collecting the requirements.",
        )


