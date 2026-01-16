"""Handlers for user story creation under epics."""

import logging

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


def handle_create_stories_confirm(ack, body, client: WebClient, action):
    """Handle confirmation to create user stories."""
    ack()
    _run_async(_handle_create_stories_confirm_async(body, client, action))


async def _handle_create_stories_confirm_async(body, client: WebClient, action):
    """Create user stories in Jira under the epic."""
    from src.jira.client import JiraService
    from src.jira.types import JiraCreateRequest, JiraIssueType, JiraPriority
    from src.config.settings import get_settings
    from src.slack.pending_stories import get_pending_stories_store

    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    user_id = body["user"]["id"]

    # Get pending stories from store
    pending_id = action.get("value", "")
    store = get_pending_stories_store()
    pending = store.get(pending_id)

    if not pending:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Error: Story data expired or not found. Please try generating stories again.",
        )
        return

    epic_key = pending.epic_key
    stories = pending.stories

    # Remove from store after retrieval
    store.remove(pending_id)

    # Create stories in Jira
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Creating {len(stories)} stories under *{epic_key}*...",
    )

    try:
        settings = get_settings()
        jira_service = JiraService(settings)
        project_key = epic_key.split("-")[0]

        created_keys = []
        errors = []

        for story in stories:
            title = story.get("title", "Untitled Story")
            description = story.get("description", "")
            criteria = story.get("acceptance_criteria", [])

            # Build full description with acceptance criteria
            full_description = description
            if criteria:
                full_description += "\n\nh3. Acceptance Criteria\n"
                full_description += "\n".join(f"* {c}" for c in criteria)

            request = JiraCreateRequest(
                project_key=project_key,
                summary=title,
                description=full_description,
                issue_type=JiraIssueType.STORY,
                priority=JiraPriority.MEDIUM,
                epic_key=epic_key,  # Links to epic
            )

            try:
                issue = await jira_service.create_issue(request)
                created_keys.append(issue.key)
                logger.info(f"Created story {issue.key} under epic {epic_key}")
            except Exception as e:
                logger.error(f"Failed to create story '{title}': {e}")
                errors.append(f"{title}: {str(e)}")

        await jira_service.close()

        # Report results
        if created_keys:
            # Build success message with links
            jira_url = settings.jira_url.rstrip("/")
            story_links = [f"<{jira_url}/browse/{key}|{key}>" for key in created_keys]

            success_msg = f":white_check_mark: Created {len(created_keys)} stories under *{epic_key}*:\n"
            success_msg += "\n".join(f"• {link}" for link in story_links)

            # Post to thread
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=success_msg,
            )

            # Auto-track created stories in the channel (Phase 21)
            try:
                from src.db import get_connection
                from src.slack.channel_tracker import ChannelIssueTracker

                async with get_connection() as conn:
                    tracker = ChannelIssueTracker(conn)
                    await tracker.create_tables()

                    # Track each created story
                    for story, key in zip(stories, created_keys):
                        await tracker.track(channel, key, user_id)
                        await tracker.update_sync_status(
                            channel,
                            key,
                            status="To Do",  # New stories are typically in To Do
                            summary=story.get("title", key),
                        )

                    # Also track the epic if not already tracked
                    if not await tracker.is_tracked(channel, epic_key):
                        await tracker.track(channel, epic_key, user_id)
                        await tracker.update_sync_status(
                            channel,
                            epic_key,
                            status=epic.status if epic else "Open",
                            summary=epic.summary if epic else epic_key,
                        )

                logger.info(
                    "Auto-tracked created stories",
                    extra={"story_keys": created_keys, "epic_key": epic_key, "channel": channel},
                )
            except Exception as e:
                logger.warning(f"Failed to auto-track stories: {e}")
                # Non-blocking - stories created successfully

            # Post announcement to main channel
            epic_url = f"{jira_url}/browse/{epic_key}"
            announcement_blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":sparkles: *{len(created_keys)} User Stories Created*\nLinked to epic <{epic_url}|{epic_key}>",
                    },
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "\n".join(f"• <{jira_url}/browse/{key}|{key}>" for key in created_keys),
                    },
                },
                {
                    "type": "context",
                    "elements": [
                        {"type": "mrkdwn", "text": f"Created by <@{user_id}>"},
                    ],
                },
            ]
            client.chat_postMessage(
                channel=channel,
                blocks=announcement_blocks,
                text=f"Created {len(created_keys)} stories under {epic_key}",
            )

        if errors:
            error_msg = f":warning: Failed to create {len(errors)} stories:\n"
            error_msg += "\n".join(f"• {e}" for e in errors)
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=error_msg,
            )

    except Exception as e:
        logger.error(f"Story creation failed: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"Failed to create stories: {str(e)}",
        )


def handle_create_stories_cancel(ack, body, client: WebClient, action):
    """Handle cancellation of story creation."""
    ack()
    from src.slack.pending_stories import get_pending_stories_store

    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]

    # Get epic key and clean up store
    pending_id = action.get("value", "")
    store = get_pending_stories_store()
    pending = store.get(pending_id)
    epic_key = pending.epic_key if pending else "the epic"
    store.remove(pending_id)

    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Cancelled story creation for *{epic_key}*.",
    )
