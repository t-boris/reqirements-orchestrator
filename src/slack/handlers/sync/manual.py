"""Manual sync command handlers.

Handles /maro sync command and diagnostic sync functionality.
"""

import json
import logging
from typing import Optional

from slack_sdk.web import WebClient

logger = logging.getLogger(__name__)


async def handle_maro_sync(
    channel_id: str,
    client: WebClient,
    user_id: str,
    auto_mode: bool = False,
) -> None:
    """Handle /maro sync command.

    Args:
        channel_id: Slack channel ID
        client: Slack WebClient
        user_id: User who invoked command
        auto_mode: If True, apply auto-apply changes immediately
    """
    from src.db import get_connection
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.slack.sync_engine import SyncEngine
    from src.slack.handlers.sync.blocks import build_sync_summary_blocks

    try:
        settings = get_settings()
        jira_service = JiraService(settings)
        jira_url = settings.jira_url.rstrip("/")

        # Get channel name
        try:
            info = client.conversations_info(channel=channel_id)
            channel_name = info.get("channel", {}).get("name", channel_id)
        except Exception:
            channel_name = channel_id

        async with get_connection() as conn:
            engine = SyncEngine(jira_service, jira_url)
            plan = await engine.detect_changes(channel_id, conn)

            if auto_mode and plan.auto_apply:
                # Apply changes immediately
                results = await engine.apply_changes(plan.auto_apply, channel_id, conn)

                # Build results message
                success_count = sum(1 for r in results if r.success)
                fail_count = len(results) - success_count

                if fail_count == 0:
                    text = f":white_check_mark: Applied {success_count} change{'s' if success_count != 1 else ''} to Jira"
                else:
                    text = f":white_check_mark: Applied {success_count} change{'s' if success_count != 1 else ''}, :x: {fail_count} failed"

                client.chat_postMessage(
                    channel=channel_id,
                    text=text,
                )

                # Show any remaining conflicts
                if plan.needs_review:
                    blocks = build_sync_summary_blocks(channel_name, plan, jira_url)
                    client.chat_postMessage(
                        channel=channel_id,
                        text="Sync conflicts need review",
                        blocks=blocks,
                    )
            else:
                # Show sync summary
                blocks = build_sync_summary_blocks(channel_name, plan, jira_url)
                client.chat_postMessage(
                    channel=channel_id,
                    text=f"Jira Sync for #{channel_name}",
                    blocks=blocks,
                )

        await jira_service.close()

    except Exception as e:
        logger.error(f"Sync command failed: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel_id,
            text="Sorry, I couldn't check sync status. Please try again.",
        )


async def handle_sync_command(
    client: WebClient,
    channel_id: str,
    user_id: str,
    thread_ts: Optional[str] = None,
) -> None:
    """Handle /maro sync diagnostic command.

    Uses the new JiraSyncService for comprehensive reconciliation report.

    1. Post initial "Syncing..." message
    2. Run JiraSyncService.sync_channel()
    3. Update message with full report

    Args:
        client: Slack WebClient
        channel_id: Slack channel ID
        user_id: User who invoked command
        thread_ts: Optional thread timestamp for response
    """
    from src.db import get_connection
    from src.db.jira_registry import JiraRegistryStore
    from src.jira.client import JiraService
    from src.config.settings import get_settings
    from src.sync.jira_sync import JiraSyncService
    from src.slack.blocks.sync import build_sync_report_blocks

    # Post initial "Syncing..." message
    msg = client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=":arrows_counterclockwise: Syncing with Jira...",
    )
    message_ts = msg.get("ts")

    jira_service = None
    try:
        settings = get_settings()
        jira_service = JiraService(settings)
        jira_url = settings.jira_url.rstrip("/")

        async with get_connection() as conn:
            registry = JiraRegistryStore(conn)
            sync_service = JiraSyncService(jira_service, registry)

            # Run sync
            result = await sync_service.sync_channel(channel_id)

        # Build report blocks
        blocks = build_sync_report_blocks(result, jira_base_url=jira_url)

        # Update message with full report
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text="Sync report",
            blocks=blocks,
        )

        logger.info(
            "Sync command completed",
            extra={
                "channel_id": channel_id,
                "user_id": user_id,
                "total_checked": result.total_checked,
                "changed": len(result.changed),
                "missing_locally": len(result.missing_locally),
                "local_only": len(result.local_only),
            },
        )

    except Exception as e:
        logger.error(f"Sync command failed: {e}", exc_info=True)
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f":x: Sync failed: {str(e)}",
            blocks=[{
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":x: Sync failed: {str(e)}",
                }
            }],
        )
    finally:
        if jira_service:
            await jira_service.close()


async def handle_sync_track_all(
    client: WebClient,
    channel_id: str,
    user_id: str,
    keys: list[str],
    response_url: str,
) -> None:
    """Handle 'Track all' button click.

    Register all provided keys as 'tracked' in registry.
    Update original message to show success.

    Args:
        client: Slack WebClient
        channel_id: Slack channel ID
        user_id: User who clicked
        keys: List of Jira issue keys to track
        response_url: Response URL for updating original message
    """
    from src.db import get_connection
    from src.db.jira_registry import JiraRegistryStore

    try:
        async with get_connection() as conn:
            registry = JiraRegistryStore(conn)

            for key in keys:
                await registry.register(
                    channel_id=channel_id,
                    jira_key=key,
                    link_type="tracked",
                    linked_by=user_id,
                )

        logger.info(
            "Tracked all missing issues",
            extra={
                "channel_id": channel_id,
                "user_id": user_id,
                "keys": keys,
                "count": len(keys),
            },
        )

        # Update via response_url (for interactive message updates)
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await session.post(
                response_url,
                json={
                    "replace_original": True,
                    "text": f":white_check_mark: Tracked {len(keys)} issue{'s' if len(keys) != 1 else ''}",
                    "blocks": [{
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":white_check_mark: Tracked {len(keys)} issue{'s' if len(keys) != 1 else ''}: {', '.join(keys[:5])}{'...' if len(keys) > 5 else ''}",
                        }
                    }],
                },
            )

    except Exception as e:
        logger.error(f"Failed to track issues: {e}", exc_info=True)
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await session.post(
                response_url,
                json={
                    "replace_original": False,
                    "text": f":x: Failed to track issues: {str(e)}",
                },
            )


async def handle_sync_track_selected(
    client: WebClient,
    channel_id: str,
    user_id: str,
    keys: list[str],
) -> None:
    """Handle 'Track selected' - show modal with checkboxes.

    Args:
        client: Slack WebClient
        channel_id: Channel ID
        user_id: User ID
        keys: Available keys to select from
    """
    # This would open a modal - for now just track all
    # TODO: Implement modal selection if needed
    logger.info(
        "Track selected triggered - using track all for now",
        extra={
            "channel_id": channel_id,
            "user_id": user_id,
            "keys": keys,
        },
    )


async def handle_sync_remove(
    client: WebClient,
    channel_id: str,
    user_id: str,
    key: str,
    response_url: str,
) -> None:
    """Handle 'Remove from tracking' button click.

    Unregister the key from registry.
    Update original message.

    Args:
        client: Slack WebClient
        channel_id: Slack channel ID
        user_id: User who clicked
        key: Jira issue key to remove
        response_url: Response URL for updating original message
    """
    from src.db import get_connection
    from src.db.jira_registry import JiraRegistryStore

    try:
        async with get_connection() as conn:
            registry = JiraRegistryStore(conn)
            removed = await registry.unregister(channel_id, key)

        if removed:
            logger.info(
                "Removed issue from tracking",
                extra={
                    "channel_id": channel_id,
                    "user_id": user_id,
                    "key": key,
                },
            )
            result_text = f":white_check_mark: Removed {key} from tracking"
        else:
            result_text = f":warning: {key} was not tracked"

        # Update via response_url
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await session.post(
                response_url,
                json={
                    "replace_original": True,
                    "text": result_text,
                    "blocks": [{
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": result_text,
                        }
                    }],
                },
            )

    except Exception as e:
        logger.error(f"Failed to remove issue: {e}", exc_info=True)
        import aiohttp
        async with aiohttp.ClientSession() as session:
            await session.post(
                response_url,
                json={
                    "replace_original": False,
                    "text": f":x: Failed to remove {key}: {str(e)}",
                },
            )
