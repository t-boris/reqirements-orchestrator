"""Handlers for user story creation under epics."""

import json
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

    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    user_id = body["user"]["id"]

    # Parse button value
    try:
        value_data = json.loads(action.get("value", "{}"))
        epic_key = value_data.get("epic_key")
        stories = value_data.get("stories", [])
    except json.JSONDecodeError:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Error: Invalid story data. Please try again.",
        )
        return

    if not epic_key or not stories:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="Error: Missing epic or stories data. Please try again.",
        )
        return

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

            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=success_msg,
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
    channel = body["channel"]["id"]
    thread_ts = body["message"].get("thread_ts") or body["message"]["ts"]
    epic_key = action.get("value", "the epic")

    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Cancelled story creation for *{epic_key}*.",
    )
