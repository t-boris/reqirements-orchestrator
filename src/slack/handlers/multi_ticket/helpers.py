"""Helper functions for multi-ticket workflow.

Contains shared helper functions for:
- Announcement posting after batch creation
- Auto-tracking created tickets
"""
import logging

from slack_sdk.web import WebClient

logger = logging.getLogger(__name__)


async def post_creation_announcement(
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
    if epics or stories:
        if epics:
            epic_list = ", ".join(e.get("jira_key", "") for e in epics)
            channel_text = f":white_check_mark: Created tickets: {epic_list}"
            if stories:
                channel_text += f" with {len(stories)} stories"
        else:
            # Only stories, no epics
            story_list = ", ".join(s.get("jira_key", "") for s in stories[:3])
            if len(stories) > 3:
                story_list += f" +{len(stories) - 3} more"
            channel_text = f":white_check_mark: Created {len(stories)} tickets: {story_list}"
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


async def track_created_tickets(
    results: list[dict],
    channel_id: str,
    user_id: str,
) -> None:
    """Auto-track all created tickets in channel.

    Integrates with Phase 21's channel tracking and Jira Registry.
    Non-blocking - failures are logged but don't interrupt the user-facing operation.

    Args:
        results: Creation results with jira_key, title, type, success
        channel_id: Slack channel ID
        user_id: User who triggered creation
    """
    from src.db import get_connection
    from src.slack.channel_tracker import ChannelIssueTracker
    from src.db.jira_registry import JiraRegistryStore

    try:
        async with get_connection() as conn:
            tracker = ChannelIssueTracker(conn)
            await tracker.create_tables()

            registry = JiraRegistryStore(conn)
            await registry.create_tables()

            tracked_count = 0
            registered_count = 0
            for result in results:
                if not result.get("success"):
                    continue

                jira_key = result.get("jira_key", "")
                if not jira_key:
                    continue

                # Track in ChannelIssueTracker
                try:
                    await tracker.track(
                        channel_id=channel_id,
                        issue_key=jira_key,
                        tracked_by=user_id,
                    )
                    tracked_count += 1
                except Exception as e:
                    logger.warning(f"Failed to track issue {jira_key}: {e}")

                # Register in JiraRegistry with summary and issue_type
                try:
                    await registry.register(
                        channel_id=channel_id,
                        jira_key=jira_key,
                        link_type="owned",
                        linked_by=user_id,
                        summary=result.get("title", ""),
                        issue_type=result.get("type", ""),
                    )
                    registered_count += 1
                except Exception as e:
                    logger.warning(f"Failed to register issue {jira_key} in registry: {e}")

            logger.info(
                "Auto-tracked created tickets",
                extra={
                    "channel_id": channel_id,
                    "tracked_count": tracked_count,
                    "registered_count": registered_count,
                },
            )

            # Trigger board refresh if board exists
            from src.slack.channel_tracker import trigger_board_refresh
            from src.config.settings import settings
            await trigger_board_refresh(channel_id, settings.jira_url)

    except Exception as e:
        # Non-blocking - log but don't fail the operation
        logger.warning(f"Failed to auto-track tickets: {e}")


# Aliases for backward compatibility with internal code
_post_creation_announcement = post_creation_announcement
_track_created_tickets = track_created_tickets
