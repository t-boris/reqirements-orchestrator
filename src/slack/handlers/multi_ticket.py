"""Handlers for multi-ticket workflow.

Handles actions from multi-ticket preview:
- Quantity confirmation (>3 items)
- Split into batches
- Edit individual item (epic/story)
- Edit submit and preview refresh
- Remove item
- Approve all
- Cancel
"""
import json
import logging
from typing import Optional

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async
from src.graph.runner import get_runner
from src.slack.session import SessionIdentity

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


def handle_multi_ticket_edit_item(ack, body: dict, client: WebClient) -> None:
    """Handle edit item button click.

    Opens modal to edit item (epic or story) with all fields.

    Args:
        ack: Slack ack function
        body: Slack action body
        client: Slack WebClient for API calls
    """
    ack()
    _run_async(_handle_multi_ticket_edit_item_async(body, client))


# Keep old name as alias for backward compatibility with existing router
handle_multi_ticket_edit_story = handle_multi_ticket_edit_item


async def _handle_multi_ticket_edit_item_async(body: dict, client: WebClient) -> None:
    """Async handler for multi-ticket edit item.

    1. Parse item_id from action_id
    2. Find item in state's multi_ticket_state.items
    3. Open modal with form fields
    """
    trigger_id = body.get("trigger_id")
    if not trigger_id:
        logger.warning("Missing trigger_id in edit_item body")
        return

    channel_id = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("message", {}).get("thread_ts") or message_ts

    if not channel_id:
        logger.warning("Missing channel_id in edit_item body")
        return

    item_id = _extract_item_id(body)
    ui_version = _extract_ui_version(body)

    logger.info(
        "Multi-ticket edit item requested",
        extra={"item_id": item_id, "ui_version": ui_version, "channel_id": channel_id},
    )

    # Get state to find the item
    team_id = body.get("team", {}).get("id", "unknown")
    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )

    try:
        runner = get_runner(identity)
        state = await runner._get_current_state()
    except Exception as e:
        logger.error(f"Failed to get state for edit_item: {e}", exc_info=True)
        return

    multi_ticket_state = state.get("multi_ticket_state")
    if not multi_ticket_state:
        logger.warning("No multi_ticket_state found")
        return

    items = multi_ticket_state.get("items", [])
    item = None
    for i in items:
        if i.get("id") == item_id:
            item = i
            break

    if not item:
        logger.warning(f"Item {item_id} not found in multi_ticket_state")
        return

    # Build and open modal
    modal_view = _build_edit_item_modal(
        item=item,
        channel_id=channel_id,
        thread_ts=thread_ts,
        message_ts=message_ts,
    )

    try:
        client.views_open(
            trigger_id=trigger_id,
            view=modal_view,
        )
    except Exception as e:
        logger.error(f"Failed to open edit item modal: {e}", exc_info=True)


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

    channel_id = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("message", {}).get("thread_ts") or message_ts
    team_id = body.get("team", {}).get("id", "unknown")
    user_id = body.get("user", {}).get("id", "unknown")

    if not channel_id or not message_ts:
        logger.warning("Missing channel_id or message_ts in approve body")
        return

    # Check ui_version from action value for stale button detection
    ui_version = _extract_ui_version(body)

    logger.info(
        "Multi-ticket approve requested",
        extra={
            "channel": channel_id,
            "message_ts": message_ts,
            "user_id": user_id,
            "ui_version": ui_version,
        },
    )

    # Get items from state
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
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text="No items to create.",
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
        await _post_creation_announcement(client, channel_id, thread_ts, results, user_id)

        # Auto-track created tickets
        await _track_created_tickets(results, channel_id, user_id)

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


async def _post_creation_announcement(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    results: list[dict],
    user_id: str,
) -> None:
    """Post rich announcement after batch creation.

    Format:
    - Header with count
    - Epics section with links
    - Stories section with links and parent references
    - Failures section (if any)
    - Footer note

    Args:
        client: Slack WebClient for API calls
        channel_id: Channel ID to post to
        thread_ts: Thread timestamp for reply
        results: Creation results with jira_key, title, type, success, error
        user_id: User who triggered creation
    """
    success_count = sum(1 for r in results if r.get("success"))
    failure_count = sum(1 for r in results if not r.get("success"))

    # Build epic key lookup for parent references
    epic_keys: dict[str, str] = {}
    for r in results:
        if r.get("type") == "epic" and r.get("success"):
            epic_keys[r.get("item_id", "")] = r.get("jira_key", "")

    # Separate by type
    epics = [r for r in results if r.get("type") == "epic" and r.get("success")]
    stories = [r for r in results if r.get("type") == "story" and r.get("success")]
    failures = [r for r in results if not r.get("success")]

    # Build announcement text
    lines = []

    # Header
    if failure_count == 0:
        lines.append(f":tada: Created {success_count} Jira tickets")
    else:
        lines.append(f":warning: Created {success_count} of {len(results)} Jira tickets ({failure_count} failed)")

    lines.append("")

    # Epics section
    if epics:
        lines.append(":dart: *Epics:*")
        for epic in epics:
            jira_key = epic.get("jira_key", "")
            jira_url = epic.get("jira_url", "")
            title = epic.get("title", "")
            if jira_url:
                lines.append(f"  - <{jira_url}|{jira_key}> {title}")
            else:
                lines.append(f"  - {jira_key} {title}")
        lines.append("")

    # Stories section
    if stories:
        lines.append(":memo: *Stories:*")
        for story in stories:
            jira_key = story.get("jira_key", "")
            jira_url = story.get("jira_url", "")
            title = story.get("title", "")
            parent_id = story.get("parent_id")

            story_text = f"<{jira_url}|{jira_key}>" if jira_url else jira_key
            story_text += f" {title}"

            # Add parent reference
            if parent_id and parent_id in epic_keys:
                parent_key = epic_keys[parent_id]
                story_text += f" (under {parent_key})"

            lines.append(f"  - {story_text}")
        lines.append("")

    # Failures section
    if failures:
        lines.append(":x: *Failed:*")
        for fail in failures:
            title = fail.get("title", "")
            error = fail.get("error", "Unknown error")
            # Truncate long errors
            if len(error) > 80:
                error = error[:80] + "..."
            lines.append(f"  - {title} - {error}")
        lines.append("")

    # Footer
    lines.append("_All tickets linked to this thread for context._")

    announcement_text = "\n".join(lines)

    # Post announcement to thread
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=announcement_text,
    )

    # Also post to main channel for context visibility
    # This allows the bot to see the ticket key when user asks from channel level
    if epics:
        epic_list = ", ".join(e.get("jira_key", "") for e in epics)
        channel_text = f":white_check_mark: Created tickets: {epic_list}"
        if stories:
            channel_text += f" with {len(stories)} stories"
        client.chat_postMessage(
            channel=channel_id,
            # No thread_ts - posts to main channel
            text=channel_text,
        )

    logger.info(
        "Posted creation announcement",
        extra={
            "channel_id": channel_id,
            "success_count": success_count,
            "failure_count": failure_count,
        },
    )


async def _track_created_tickets(
    results: list[dict],
    channel_id: str,
    user_id: str,
) -> None:
    """Auto-track all created tickets in channel.

    Integrates with Phase 21's channel tracking. Non-blocking - failures
    are logged but don't interrupt the user-facing operation.

    Args:
        results: Creation results with jira_key, title, type, success
        channel_id: Slack channel ID
        user_id: User who triggered creation
    """
    from src.db import get_connection
    from src.slack.channel_tracker import ChannelIssueTracker

    try:
        async with get_connection() as conn:
            tracker = ChannelIssueTracker(conn)
            await tracker.create_tables()

            tracked_count = 0
            for result in results:
                if not result.get("success"):
                    continue

                jira_key = result.get("jira_key", "")
                if not jira_key:
                    continue

                try:
                    await tracker.track(
                        channel_id=channel_id,
                        issue_key=jira_key,
                        tracked_by=user_id,
                    )
                    tracked_count += 1
                except Exception as e:
                    logger.warning(f"Failed to track issue {jira_key}: {e}")

            logger.info(
                "Auto-tracked created tickets",
                extra={
                    "channel_id": channel_id,
                    "tracked_count": tracked_count,
                },
            )

            # Trigger board refresh if board exists
            from src.slack.channel_tracker import trigger_board_refresh
            from src.config.settings import settings
            await trigger_board_refresh(channel_id, settings.jira_url)

    except Exception as e:
        # Non-blocking - log but don't fail the operation
        logger.warning(f"Failed to auto-track tickets: {e}")


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
        await _track_created_tickets(retry_results, channel_id, user_id)

    finally:
        await jira.close()


def handle_multi_ticket_cancel(ack, body: dict, client: WebClient) -> None:
    """Handle cancel button click.

    Cancels multi-ticket creation and clears state.

    Args:
        ack: Slack ack function
        body: Slack action body
        client: Slack WebClient for API calls
    """
    ack()
    _run_async(_handle_multi_ticket_cancel_async(body, client))


async def _handle_multi_ticket_cancel_async(body: dict, client: WebClient) -> None:
    """Cancel multi-ticket creation.

    If user has made edits, show confirmation modal before cancelling.
    Otherwise, proceed with direct cancel.
    """
    channel_id = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("message", {}).get("thread_ts") or message_ts
    team_id = body.get("team", {}).get("id", "unknown")
    user_id = body.get("user", {}).get("id")
    trigger_id = body.get("trigger_id")

    if not channel_id or not message_ts:
        logger.warning("Missing channel_id or message_ts in cancel body")
        return

    logger.info(
        "Multi-ticket cancel requested",
        extra={
            "channel": channel_id,
            "message_ts": message_ts,
            "user_id": user_id,
        },
    )

    # Check if any edits were made
    identity = SessionIdentity(team_id=team_id, channel_id=channel_id, thread_ts=thread_ts)
    try:
        runner = get_runner(identity)
        state = await runner._get_current_state()
    except Exception as e:
        logger.error(f"Failed to get state for cancel: {e}", exc_info=True)
        # Proceed with cancel anyway
        await _do_cancel(client, channel_id, message_ts, thread_ts, None)
        return

    multi_state = state.get("multi_ticket_state", {})
    has_edits = multi_state.get("has_edits", False)

    if has_edits and trigger_id:
        # Show confirmation modal
        client.views_open(
            trigger_id=trigger_id,
            view={
                "type": "modal",
                "callback_id": "multi_ticket_cancel_confirm",
                "title": {"type": "plain_text", "text": "Discard Changes?"},
                "submit": {"type": "plain_text", "text": "Discard"},
                "close": {"type": "plain_text", "text": "Keep Editing"},
                "private_metadata": json.dumps({
                    "message_ts": message_ts,
                    "thread_ts": thread_ts,
                    "channel_id": channel_id,
                }),
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "You've made changes to the items. Are you sure you want to discard them?",
                        },
                    },
                ],
            },
        )
    else:
        # Direct cancel
        await _do_cancel(client, channel_id, message_ts, thread_ts, runner)


async def _do_cancel(
    client: WebClient,
    channel_id: str,
    message_ts: str,
    thread_ts: str,
    runner,
) -> None:
    """Execute the cancel action.

    Args:
        client: Slack WebClient
        channel_id: Channel ID
        message_ts: Preview message timestamp to delete
        thread_ts: Thread timestamp for reply
        runner: Graph runner (optional) to clear state
    """
    # Delete preview message
    try:
        client.chat_delete(channel=channel_id, ts=message_ts)
    except Exception as e:
        logger.warning(f"Failed to delete preview message: {e}")
        # Fall back to updating the message
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="Multi-ticket creation cancelled.",
            blocks=[],
        )

    # Post dismissal
    client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text="Multi-ticket creation cancelled.",
    )

    # Clear state
    if runner:
        try:
            await runner.update_state({"multi_ticket_state": None})
        except Exception as e:
            logger.warning(f"Failed to clear multi_ticket_state: {e}")

    logger.info(
        "Multi-ticket creation cancelled",
        extra={"channel_id": channel_id},
    )


def handle_multi_ticket_cancel_confirm(ack, body, client: WebClient, view) -> None:
    """Handle cancel confirmation modal submission.

    Args:
        ack: Slack ack function
        body: Slack view submission body
        client: Slack WebClient
        view: Slack view object
    """
    ack()
    _run_async(_handle_multi_ticket_cancel_confirm_async(body, client, view))


async def _handle_multi_ticket_cancel_confirm_async(body, client: WebClient, view) -> None:
    """Execute cancel after confirmation."""
    private_metadata_raw = view.get("private_metadata", "{}")
    try:
        private_metadata = json.loads(private_metadata_raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse private_metadata: {private_metadata_raw}")
        return

    message_ts = private_metadata.get("message_ts", "")
    thread_ts = private_metadata.get("thread_ts", "")
    channel_id = private_metadata.get("channel_id", "")

    if not channel_id or not message_ts:
        logger.warning("Missing channel_id or message_ts in cancel confirm")
        return

    # Get runner to clear state
    team_id = body.get("team", {}).get("id", "unknown")
    identity = SessionIdentity(team_id=team_id, channel_id=channel_id, thread_ts=thread_ts)

    runner = None
    try:
        runner = get_runner(identity)
    except Exception as e:
        logger.warning(f"Failed to get runner for cancel confirm: {e}")

    await _do_cancel(client, channel_id, message_ts, thread_ts, runner)


def _extract_item_id(body: dict) -> Optional[str]:
    """Extract item ID from action_id.

    Action ID format: multi_ticket_edit_item:{item_id}:{ui_version}
    or multi_ticket_remove_item:{item_id}:{ui_version}

    Args:
        body: Slack action body

    Returns:
        Item ID or None if not found
    """
    actions = body.get("actions", [])
    if actions:
        action_id = actions[0].get("action_id", "")
        # Format: multi_ticket_edit_item:item_id:ui_version
        parts = action_id.split(":")
        if len(parts) >= 2:
            return parts[1]
    return None


# Alias for backward compatibility
_extract_story_id = _extract_item_id


def _extract_ui_version(body: dict) -> int:
    """Extract ui_version from action value or action_id.

    UI version is used for stale button detection. Format in action_id:
    {action_type}:{identifier}:{ui_version}

    Or in action value: {value}:{ui_version}

    Args:
        body: Slack action body

    Returns:
        UI version number (0 if not found)
    """
    actions = body.get("actions", [])
    if not actions:
        return 0

    action = actions[0]

    # Try action_id first (format: action_type:id:version)
    action_id = action.get("action_id", "")
    parts = action_id.split(":")
    if len(parts) >= 3 and parts[-1].isdigit():
        return int(parts[-1])

    # Try action value (format: value:version)
    value = action.get("value", "")
    if ":" in value:
        version_part = value.split(":")[-1]
        if version_part.isdigit():
            return int(version_part)

    return 0


def _build_edit_item_modal(
    item: dict,
    channel_id: str,
    thread_ts: str,
    message_ts: Optional[str] = None,
) -> dict:
    """Build modal view for editing a multi-ticket item.

    Args:
        item: MultiTicketItem dict with id, type, title, description, etc.
        channel_id: Slack channel ID
        thread_ts: Thread timestamp
        message_ts: Preview message timestamp for updating after edit

    Returns:
        Slack modal view structure
    """
    item_id = item.get("id", "")
    item_type = item.get("type", "story")
    title = item.get("title", "")
    description = item.get("description", "")
    problem_statement = item.get("problem_statement", "")
    acceptance_criteria = item.get("acceptance_criteria", "")

    # Build private metadata for submission handler
    private_metadata = json.dumps({
        "item_id": item_id,
        "channel_id": channel_id,
        "thread_ts": thread_ts,
        "message_ts": message_ts,
    })

    # Type selection: Epic or Story
    type_options = [
        {"text": {"type": "plain_text", "text": "Epic"}, "value": "epic"},
        {"text": {"type": "plain_text", "text": "Story"}, "value": "story"},
    ]

    # Find initial selected type
    initial_type = next(
        (opt for opt in type_options if opt["value"] == item_type),
        type_options[1],  # Default to story
    )

    modal: dict = {
        "type": "modal",
        "callback_id": "multi_ticket_edit_submit",
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "Edit Item"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            # Title input (required)
            {
                "type": "input",
                "block_id": "title_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "title",
                    "initial_value": title,
                    "placeholder": {"type": "plain_text", "text": "Enter title..."},
                },
                "label": {"type": "plain_text", "text": "Title"},
            },
            # Type selection (radio buttons)
            {
                "type": "input",
                "block_id": "type_block",
                "element": {
                    "type": "radio_buttons",
                    "action_id": "item_type",
                    "initial_option": initial_type,
                    "options": type_options,
                },
                "label": {"type": "plain_text", "text": "Type"},
            },
            # Description (multiline, required)
            {
                "type": "input",
                "block_id": "description_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "description",
                    "multiline": True,
                    "initial_value": description,
                    "placeholder": {"type": "plain_text", "text": "Enter description..."},
                },
                "label": {"type": "plain_text", "text": "Description"},
            },
            # Problem Statement (multiline, optional)
            {
                "type": "input",
                "block_id": "problem_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "problem_statement",
                    "multiline": True,
                    "initial_value": problem_statement,
                    "placeholder": {"type": "plain_text", "text": "What problem does this solve?"},
                },
                "label": {"type": "plain_text", "text": "Problem Statement"},
            },
            # Acceptance Criteria (multiline, optional)
            {
                "type": "input",
                "block_id": "acceptance_criteria_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "acceptance_criteria",
                    "multiline": True,
                    "initial_value": acceptance_criteria,
                    "placeholder": {"type": "plain_text", "text": "How do we know when this is done?"},
                },
                "label": {"type": "plain_text", "text": "Acceptance Criteria"},
            },
        ],
    }

    return modal


def handle_multi_ticket_edit_submit(ack, body, client: WebClient, view) -> None:
    """Handle edit item modal submission.

    Update item in state and refresh preview message.

    Args:
        ack: Slack ack function
        body: Slack view submission body
        client: Slack WebClient for API calls
        view: Slack view object with submitted values
    """
    ack()
    _run_async(_handle_multi_ticket_edit_submit_async(body, client, view))


async def _handle_multi_ticket_edit_submit_async(body, client: WebClient, view) -> None:
    """Update item in state and refresh preview.

    1. Parse form values from view["state"]["values"]
    2. Get item_id and message context from private_metadata
    3. Update item in multi_ticket_state.items
    4. Rebuild preview blocks with updated item
    5. Update the preview message using client.chat_update()
    """
    user_id = body.get("user", {}).get("id")
    view_state = view.get("state", {}).get("values", {})
    private_metadata_raw = view.get("private_metadata", "{}")

    # Parse private metadata
    try:
        private_metadata = json.loads(private_metadata_raw)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse private_metadata: {private_metadata_raw}")
        return

    item_id = private_metadata.get("item_id", "")
    channel_id = private_metadata.get("channel_id", "")
    thread_ts = private_metadata.get("thread_ts", "")
    message_ts = private_metadata.get("message_ts", "")

    logger.info(
        "Processing multi-ticket edit submit",
        extra={
            "item_id": item_id,
            "channel_id": channel_id,
            "user_id": user_id,
        }
    )

    if not channel_id or not thread_ts:
        logger.error("Missing channel_id or thread_ts in private_metadata")
        return

    # Parse submitted values
    title = view_state.get("title_block", {}).get("title", {}).get("value", "")
    item_type = view_state.get("type_block", {}).get("item_type", {}).get("selected_option", {}).get("value", "story")
    description = view_state.get("description_block", {}).get("description", {}).get("value", "")
    problem_statement = view_state.get("problem_block", {}).get("problem_statement", {}).get("value") or ""
    acceptance_criteria = view_state.get("acceptance_criteria_block", {}).get("acceptance_criteria", {}).get("value") or ""

    # Get runner and current state
    team_id = body.get("team", {}).get("id", "unknown")
    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )

    try:
        runner = get_runner(identity)
        state = await runner._get_current_state()
    except Exception as e:
        logger.error(f"Failed to get state for edit submit: {e}", exc_info=True)
        return

    multi_ticket_state = state.get("multi_ticket_state")
    if not multi_ticket_state:
        logger.warning("No multi_ticket_state found during edit submit")
        return

    items = multi_ticket_state.get("items", [])

    # Find and update the item
    item_found = False
    for item in items:
        if item.get("id") == item_id:
            item["title"] = title
            item["type"] = item_type
            item["description"] = description
            item["problem_statement"] = problem_statement
            item["acceptance_criteria"] = acceptance_criteria
            item_found = True
            break

    if not item_found:
        logger.warning(f"Item {item_id} not found during edit submit")
        return

    # Update state with modified items and mark as edited
    multi_ticket_state["items"] = items
    multi_ticket_state["has_edits"] = True
    ui_version = state.get("ui_version", 0) + 1

    await runner.update_state({
        "multi_ticket_state": multi_ticket_state,
        "ui_version": ui_version,
    })

    # Rebuild and update preview message
    from src.slack.blocks.multi_ticket import build_multi_ticket_preview_blocks

    # Get source context from review_artifact if available
    review_artifact = state.get("review_artifact", {})
    source_persona = review_artifact.get("persona", "")
    source_date = ""
    if review_artifact.get("frozen_at"):
        # Extract date from ISO timestamp
        frozen_at = review_artifact.get("frozen_at", "")
        if frozen_at:
            source_date = frozen_at.split("T")[0] if "T" in frozen_at else frozen_at

    preview_blocks = build_multi_ticket_preview_blocks(
        items=items,
        ui_version=ui_version,
        source_persona=source_persona,
        source_date=source_date,
    )

    # Update the preview message
    if message_ts:
        try:
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text=f"Create {len(items)} Jira Tickets",
                blocks=preview_blocks,
            )
            logger.info(
                "Preview updated after edit",
                extra={"item_id": item_id, "message_ts": message_ts},
            )
        except Exception as e:
            logger.error(f"Failed to update preview message: {e}", exc_info=True)
    else:
        logger.warning("No message_ts available to update preview")


def handle_multi_ticket_remove_item(ack, body: dict, client: WebClient) -> None:
    """Handle remove item button click.

    Remove item from state and refresh preview.

    Args:
        ack: Slack ack function
        body: Slack action body
        client: Slack WebClient for API calls
    """
    ack()
    _run_async(_handle_multi_ticket_remove_item_async(body, client))


async def _handle_multi_ticket_remove_item_async(body: dict, client: WebClient) -> None:
    """Remove item from state and refresh preview.

    1. Parse item_id from action_id
    2. Remove item from multi_ticket_state.items
    3. If item was Epic with child Stories, also remove children (or orphan them)
    4. Rebuild and update preview
    5. If only 1 item remains, show message asking about single-ticket flow
    """
    channel_id = body.get("channel", {}).get("id")
    message_ts = body.get("message", {}).get("ts")
    thread_ts = body.get("message", {}).get("thread_ts") or message_ts

    if not channel_id or not message_ts:
        logger.warning("Missing channel_id or message_ts in remove_item body")
        return

    item_id = _extract_item_id(body)
    ui_version = _extract_ui_version(body)

    logger.info(
        "Multi-ticket remove item requested",
        extra={"item_id": item_id, "channel_id": channel_id},
    )

    # Get runner and current state
    team_id = body.get("team", {}).get("id", "unknown")
    identity = SessionIdentity(
        team_id=team_id,
        channel_id=channel_id,
        thread_ts=thread_ts,
    )

    try:
        runner = get_runner(identity)
        state = await runner._get_current_state()
    except Exception as e:
        logger.error(f"Failed to get state for remove_item: {e}", exc_info=True)
        return

    multi_ticket_state = state.get("multi_ticket_state")
    if not multi_ticket_state:
        logger.warning("No multi_ticket_state found during remove")
        return

    items = multi_ticket_state.get("items", [])

    # Find the item to remove
    item_to_remove = None
    for item in items:
        if item.get("id") == item_id:
            item_to_remove = item
            break

    if not item_to_remove:
        logger.warning(f"Item {item_id} not found during remove")
        return

    # Track IDs to remove (item itself and potentially children)
    ids_to_remove = {item_id}

    # If removing an Epic, also remove its child Stories (or orphan them)
    # For now, we orphan them (clear parent_id) rather than delete
    if item_to_remove.get("type") == "epic":
        for item in items:
            if item.get("parent_id") == item_id:
                # Orphan the story by clearing parent_id
                item["parent_id"] = None
                logger.info(f"Orphaned story {item.get('id')} after epic removal")

    # Remove the item(s)
    updated_items = [item for item in items if item.get("id") not in ids_to_remove]

    # Update state
    multi_ticket_state["items"] = updated_items
    new_ui_version = state.get("ui_version", 0) + 1

    await runner.update_state({
        "multi_ticket_state": multi_ticket_state,
        "ui_version": new_ui_version,
    })

    # Handle edge case: only 1 item remains
    if len(updated_items) == 1:
        # Show message suggesting single-ticket flow
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="Only 1 item remains. Would you like to switch to the single-ticket editing experience for more detailed editing?",
            blocks=[
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"Only *1 item* remains:\n\n*{updated_items[0].get('title', 'Untitled')}*\n\nWould you like to switch to single-ticket editing for a richer editing experience?",
                    },
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Switch to Single-Ticket"},
                            "action_id": "multi_ticket_switch_to_single",
                            "style": "primary",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Keep Multi-Ticket View"},
                            "action_id": f"multi_ticket_keep_multi:{new_ui_version}",
                        },
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "Cancel"},
                            "action_id": "multi_ticket_cancel",
                            "style": "danger",
                        },
                    ],
                },
            ],
        )
        return

    # Handle edge case: no items remain
    if len(updated_items) == 0:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="All items removed. Multi-ticket creation cancelled.",
            blocks=[],
        )
        return

    # Rebuild and update preview with remaining items
    from src.slack.blocks.multi_ticket import build_multi_ticket_preview_blocks

    # Get source context from review_artifact if available
    review_artifact = state.get("review_artifact", {})
    source_persona = review_artifact.get("persona", "")
    source_date = ""
    if review_artifact.get("frozen_at"):
        frozen_at = review_artifact.get("frozen_at", "")
        if frozen_at:
            source_date = frozen_at.split("T")[0] if "T" in frozen_at else frozen_at

    preview_blocks = build_multi_ticket_preview_blocks(
        items=updated_items,
        ui_version=new_ui_version,
        source_persona=source_persona,
        source_date=source_date,
    )

    try:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f"Create {len(updated_items)} Jira Tickets",
            blocks=preview_blocks,
        )
        logger.info(
            "Preview updated after remove",
            extra={"removed_item_id": item_id, "remaining_count": len(updated_items)},
        )
    except Exception as e:
        logger.error(f"Failed to update preview after remove: {e}", exc_info=True)
