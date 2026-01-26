"""Ticket creation flow for multi-ticket workflow.

Handles:
- Quantity confirmation (>3 items)
- Split into batches
- Approve all / batch creation
- Retry failed items
"""
import json
import logging

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async
from src.graph.runner import get_runner
from src.slack.session import SessionIdentity
from src.slack.handlers.multi_ticket.helpers import (
    post_creation_announcement,
    track_created_tickets,
)

logger = logging.getLogger(__name__)


def handle_multi_ticket_confirm_quantity(ack, body: dict, client: WebClient) -> None:
    """Handle quantity confirmation (>3 items).

    When user confirms they want to create more than MULTI_TICKET_QUANTITY_THRESHOLD
    items, update state and continue to preview.

    Args:
        ack: Slack ack function
        body: Slack action body
        client: Slack WebClient for API calls
    """
    ack()
    _run_async(_handle_multi_ticket_confirm_quantity_async(body, client))


async def _handle_multi_ticket_confirm_quantity_async(body: dict, client: WebClient) -> None:
    """Async handler for multi-ticket quantity confirmation."""
    channel = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")

    if not channel or not message_ts:
        logger.warning("Missing channel or message_ts in confirm_quantity body")
        return

    # Update message to show confirmation received
    client.chat_update(
        channel=channel,
        ts=message_ts,
        text="Quantity confirmed. Preparing preview...",
        blocks=[],
    )

    logger.info(
        "Multi-ticket quantity confirmed",
        extra={"channel": channel, "message_ts": message_ts},
    )

    # Note: State update + preview will be triggered by graph runner
    # This handler just updates the UI immediately


def handle_multi_ticket_split(ack, body: dict, client: WebClient) -> None:
    """Handle split into batches request.

    When batch is too large, user can choose to split into smaller batches.
    Bot creates Epic first, then adds stories in groups.

    Args:
        ack: Slack ack function
        body: Slack action body
        client: Slack WebClient for API calls
    """
    ack()
    _run_async(_handle_multi_ticket_split_async(body, client))


async def _handle_multi_ticket_split_async(body: dict, client: WebClient) -> None:
    """Async handler for multi-ticket split."""
    channel = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")

    if not channel or not message_ts:
        logger.warning("Missing channel or message_ts in split body")
        return

    client.chat_update(
        channel=channel,
        ts=message_ts,
        text="Splitting into batches. I'll create the Epic first, then add stories in groups.",
        blocks=[],
    )

    logger.info(
        "Multi-ticket split requested",
        extra={"channel": channel, "message_ts": message_ts},
    )

    # TODO: Implement batch splitting logic in graph runner
    # This will be wired up when the full multi-ticket flow is integrated


def handle_multi_ticket_approve(ack, body: dict, client: WebClient) -> None:
    """Handle approve all button click.

    Triggers batch creation in Jira.

    Args:
        ack: Slack ack function
        body: Slack action body
        client: Slack WebClient for API calls
    """
    ack()
    _run_async(_handle_multi_ticket_approve_async(body, client))


async def _handle_multi_ticket_approve_async(body: dict, client: WebClient) -> None:
    """Create all tickets and show progress.

    1. Get items from state
    2. Sort: Epics first, then Stories
    3. Create tickets with progress updates
    4. Post announcement
    5. Auto-track created tickets
    6. Clear multi_ticket_state
    """
    from src.config.settings import get_settings
    from src.jira.client import JiraService
    from src.jira.types import JiraCreateRequest, JiraIssueType, JiraPriority
    from src.slack.blocks.multi_ticket import build_creation_progress_blocks
    from src.slack.handlers.multi_ticket.linking import extract_ui_version

    channel_id = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")
    team_id = body.get("team", {}).get("id", "unknown")
    user_id = body.get("user", {}).get("id", "unknown")

    if not channel_id or not message_ts:
        logger.warning("Missing channel_id or message_ts in approve body")
        return

    # Extract thread_ts from button value (contains original thread context)
    # This is critical for state lookup - message thread_ts may differ from state thread_ts
    action = body.get("actions", [{}])[0]
    button_value_raw = action.get("value", "{}")
    try:
        button_value = json.loads(button_value_raw)
        thread_ts = button_value.get("thread_ts", "")
    except (json.JSONDecodeError, TypeError):
        # Fallback to message context (legacy buttons)
        thread_ts = body.get("message", {}).get("thread_ts") or message_ts
        logger.warning(f"Could not parse button value, falling back to message thread_ts: {thread_ts}")

    if not thread_ts:
        thread_ts = body.get("message", {}).get("thread_ts") or message_ts

    # Check ui_version from action value for stale button detection
    ui_version = extract_ui_version(body)

    logger.info(
        "Multi-ticket approve requested",
        extra={
            "channel": channel_id,
            "message_ts": message_ts,
            "thread_ts": thread_ts,
            "user_id": user_id,
            "ui_version": ui_version,
        },
    )

    # Get items from state using the original thread_ts from button value
    identity = SessionIdentity(team_id=team_id, channel_id=channel_id, thread_ts=thread_ts)
    try:
        runner = get_runner(identity)
        state = await runner._get_current_state()
    except Exception as e:
        logger.error(f"Failed to get state for approve: {e}", exc_info=True)
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="Failed to get state. Please try again.",
            blocks=[],
        )
        return

    multi_state = state.get("multi_ticket_state", {})
    items = multi_state.get("items", [])

    if not items:
        logger.warning(
            "No items found in multi_ticket_state",
            extra={
                "channel": channel_id,
                "thread_ts": thread_ts,
                "multi_state_keys": list(multi_state.keys()) if multi_state else [],
                "state_keys": list(state.keys()) if state else [],
            }
        )
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="No items to create. The preview may have expired - please regenerate the preview.",
        )
        return

    # Get project from settings
    settings = get_settings()
    project_key = settings.jira_default_project
    if not project_key:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="No default Jira project configured. Please set JIRA_DEFAULT_PROJECT.",
        )
        return

    # Sort: Epics first, then Stories
    epics = [i for i in items if i.get("type") == "epic"]
    stories = [i for i in items if i.get("type") == "story"]
    ordered = epics + stories

    # Create tickets with progress updates
    results: list[dict] = []
    jira = JiraService(settings)

    try:
        for idx, item in enumerate(ordered):
            # Update preview with progress (checkmark for done, spinner for current)
            progress_blocks = build_creation_progress_blocks(ordered, results, current_idx=idx)
            client.chat_update(channel=channel_id, ts=message_ts, blocks=progress_blocks)

            try:
                # Resolve parent_item_id to Jira key if story has parent
                parent_key = None
                if item.get("parent_id"):
                    parent_result = next(
                        (r for r in results if r["item_id"] == item["parent_id"] and r["success"]),
                        None,
                    )
                    if parent_result:
                        parent_key = parent_result["jira_key"]

                # Create ticket
                issue_type = JiraIssueType.EPIC if item.get("type") == "epic" else JiraIssueType.STORY

                request = JiraCreateRequest(
                    project_key=project_key,
                    summary=item.get("title", "Untitled"),
                    description=item.get("description", ""),
                    issue_type=issue_type,
                    priority=JiraPriority.MEDIUM,
                    epic_key=parent_key,
                )

                jira_issue = await jira.create_issue(request)

                results.append({
                    "item_id": item.get("id"),
                    "jira_key": jira_issue.key,
                    "jira_url": jira_issue.url,
                    "title": item.get("title", "Untitled"),
                    "type": item.get("type", "story"),
                    "parent_id": item.get("parent_id"),
                    "success": True,
                })

                logger.info(
                    "Created ticket",
                    extra={
                        "item_id": item.get("id"),
                        "jira_key": jira_issue.key,
                        "type": item.get("type"),
                    },
                )

                # Bind thread to first epic created for contextual references
                if item.get("type") == "epic" and idx == 0:
                    try:
                        from src.slack.thread_bindings import get_binding_store

                        binding_store = get_binding_store()
                        await binding_store.bind(
                            channel_id=channel_id,
                            thread_ts=thread_ts,
                            issue_key=jira_issue.key,
                            bound_by="system",
                        )
                    except Exception as e:
                        logger.warning(f"Failed to bind thread to epic: {e}")

            except Exception as e:
                logger.error(f"Failed to create ticket for item {item.get('id')}: {e}")
                results.append({
                    "item_id": item.get("id"),
                    "title": item.get("title", "Untitled"),
                    "type": item.get("type", "story"),
                    "parent_id": item.get("parent_id"),
                    "success": False,
                    "error": str(e),
                })

        # Final progress update
        progress_blocks = build_creation_progress_blocks(ordered, results, current_idx=None)
        client.chat_update(channel=channel_id, ts=message_ts, blocks=progress_blocks)

        # Post announcement
        await post_creation_announcement(client, channel_id, thread_ts, results, user_id)

        # Auto-track created tickets
        await track_created_tickets(results, channel_id, user_id)

        # Check if any failures - if so, store results for retry, otherwise clear state
        failure_count = sum(1 for r in results if not r.get("success"))
        if failure_count > 0:
            # Store results for retry
            multi_state["last_results"] = results
            await runner.update_state({"multi_ticket_state": multi_state})
        else:
            # Clear multi_ticket_state on success
            await runner.update_state({"multi_ticket_state": None})

    finally:
        await jira.close()


def handle_multi_ticket_retry_failed(ack, body: dict, client: WebClient) -> None:
    """Handle retry failed items button.

    Re-attempts creation of items that failed in the previous batch.

    Args:
        ack: Slack ack function
        body: Slack action body
        client: Slack WebClient for API calls
    """
    ack()
    _run_async(_handle_multi_ticket_retry_failed_async(body, client))


async def _handle_multi_ticket_retry_failed_async(body: dict, client: WebClient) -> None:
    """Retry creation of failed items.

    1. Get multi_ticket_state with last_results
    2. Filter to failed items
    3. Re-run creation for those items
    4. Update results and announcement
    """
    from src.config.settings import get_settings
    from src.jira.client import JiraService
    from src.jira.types import JiraCreateRequest, JiraIssueType, JiraPriority
    from src.slack.blocks.multi_ticket import build_creation_progress_blocks

    channel_id = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("message", {}).get("thread_ts") or message_ts
    team_id = body.get("team", {}).get("id", "unknown")
    user_id = body.get("user", {}).get("id", "unknown")

    if not channel_id or not message_ts:
        logger.warning("Missing channel_id or message_ts in retry_failed body")
        return

    logger.info(
        "Multi-ticket retry failed requested",
        extra={"channel_id": channel_id, "user_id": user_id},
    )

    # Get items and previous results from state
    identity = SessionIdentity(team_id=team_id, channel_id=channel_id, thread_ts=thread_ts)
    try:
        runner = get_runner(identity)
        state = await runner._get_current_state()
    except Exception as e:
        logger.error(f"Failed to get state for retry: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="Failed to get state. Please try again.",
        )
        return

    multi_state = state.get("multi_ticket_state", {})
    items = multi_state.get("items", [])
    last_results = multi_state.get("last_results", [])

    if not items or not last_results:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="No failed items to retry.",
        )
        return

    # Find failed item IDs
    failed_ids = {r["item_id"] for r in last_results if not r.get("success")}

    if not failed_ids:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="No failed items to retry.",
        )
        return

    # Get only failed items, preserving order
    failed_items = [i for i in items if i.get("id") in failed_ids]

    # Get project from settings
    settings = get_settings()
    project_key = settings.jira_default_project
    if not project_key:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="No default Jira project configured. Please set JIRA_DEFAULT_PROJECT.",
        )
        return

    # Build lookup for successful results (for parent references)
    success_lookup: dict[str, dict] = {
        r["item_id"]: r for r in last_results if r.get("success")
    }

    # Create tickets with progress updates
    retry_results: list[dict] = []
    jira = JiraService(settings)

    try:
        for idx, item in enumerate(failed_items):
            # Update preview with progress
            progress_blocks = build_creation_progress_blocks(failed_items, retry_results, current_idx=idx)
            client.chat_update(channel=channel_id, ts=message_ts, blocks=progress_blocks)

            try:
                # Resolve parent_id to Jira key if story has parent
                parent_key = None
                if item.get("parent_id"):
                    # First check success_lookup from previous run
                    parent_result = success_lookup.get(item["parent_id"])
                    if parent_result:
                        parent_key = parent_result.get("jira_key")
                    else:
                        # Check retry results
                        parent_retry = next(
                            (r for r in retry_results if r["item_id"] == item["parent_id"] and r["success"]),
                            None,
                        )
                        if parent_retry:
                            parent_key = parent_retry.get("jira_key")

                # Create ticket
                issue_type = JiraIssueType.EPIC if item.get("type") == "epic" else JiraIssueType.STORY

                request = JiraCreateRequest(
                    project_key=project_key,
                    summary=item.get("title", "Untitled"),
                    description=item.get("description", ""),
                    issue_type=issue_type,
                    priority=JiraPriority.MEDIUM,
                    epic_key=parent_key,
                )

                jira_issue = await jira.create_issue(request)

                retry_results.append({
                    "item_id": item.get("id"),
                    "jira_key": jira_issue.key,
                    "jira_url": jira_issue.url,
                    "title": item.get("title", "Untitled"),
                    "type": item.get("type", "story"),
                    "parent_id": item.get("parent_id"),
                    "success": True,
                })

                logger.info(
                    "Retry created ticket",
                    extra={
                        "item_id": item.get("id"),
                        "jira_key": jira_issue.key,
                        "type": item.get("type"),
                    },
                )

            except Exception as e:
                logger.error(f"Retry failed for item {item.get('id')}: {e}")
                retry_results.append({
                    "item_id": item.get("id"),
                    "title": item.get("title", "Untitled"),
                    "type": item.get("type", "story"),
                    "parent_id": item.get("parent_id"),
                    "success": False,
                    "error": str(e),
                })

        # Final progress update
        progress_blocks = build_creation_progress_blocks(failed_items, retry_results, current_idx=None)
        client.chat_update(channel=channel_id, ts=message_ts, blocks=progress_blocks)

        # Merge retry results into last_results
        # Update entries that were retried
        retry_lookup = {r["item_id"]: r for r in retry_results}
        merged_results = []
        for r in last_results:
            if r["item_id"] in retry_lookup:
                merged_results.append(retry_lookup[r["item_id"]])
            else:
                merged_results.append(r)

        # Update state with merged results
        multi_state["last_results"] = merged_results
        await runner.update_state({"multi_ticket_state": multi_state})

        # Post retry announcement
        retry_success = sum(1 for r in retry_results if r.get("success"))
        retry_fail = sum(1 for r in retry_results if not r.get("success"))

        if retry_fail == 0:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":white_check_mark: Retry succeeded: {retry_success} tickets created.",
            )
        else:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":warning: Retry completed: {retry_success} created, {retry_fail} still failing.",
            )

        # Auto-track newly created tickets
        await track_created_tickets(retry_results, channel_id, user_id)

    finally:
        await jira.close()
