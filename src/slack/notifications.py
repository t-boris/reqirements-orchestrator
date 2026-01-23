"""Targeted notification service for multi-user support.

Provides notification utilities that ping the right people, not the whole channel.
Integrates with WorkItem ownership to notify owners and watchers specifically.

Key behaviors:
- Notify owners/watchers, not everyone
- Max 2 @mentions per message (from 27.2)
- Respects mention limits to prevent spam

Phase 27.6 - Notifications & Slack UX
"""
import logging
from typing import Optional

from slack_sdk.web import WebClient

from src.slack.mention_formatter import format_user_mention, limit_mentions

logger = logging.getLogger(__name__)

MAX_MENTIONS = 2


async def notify_owners(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    workitem_id: str,
    message: str,
    *,
    fallback_user_id: Optional[str] = None,
) -> None:
    """Notify WorkItem owners about an update or question.

    Uses owners from WorkItem, falls back to creator if no owners.
    Limits to MAX_MENTIONS to prevent spam.

    Args:
        client: Slack WebClient for posting messages
        channel_id: Channel to post in
        thread_ts: Thread to reply in
        workitem_id: WorkItem UUID to get owners from
        message: Message text to send (mentions will be prepended)
        fallback_user_id: User to notify if no owners found
    """
    from src.db import get_connection
    from src.db.workitem_store import WorkItemStore

    async with get_connection() as conn:
        store = WorkItemStore(conn)
        item = await store.get(workitem_id)

    if not item:
        logger.warning(f"WorkItem not found for notification: {workitem_id}")
        if fallback_user_id:
            _send_notification(client, channel_id, thread_ts, message, [fallback_user_id])
        return

    # Get owners, fall back to creator
    recipients = item.owners if item.owners else [item.created_by]

    _send_notification(client, channel_id, thread_ts, message, recipients[:MAX_MENTIONS])


async def notify_watchers(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    workitem_id: str,
    message: str,
) -> None:
    """Notify WorkItem watchers about a status change.

    Args:
        client: Slack WebClient for posting messages
        channel_id: Channel to post in
        thread_ts: Thread to reply in
        workitem_id: WorkItem UUID to get watchers from
        message: Message text to send (mentions will be prepended)
    """
    from src.db import get_connection
    from src.db.workitem_store import WorkItemStore

    async with get_connection() as conn:
        store = WorkItemStore(conn)
        item = await store.get(workitem_id)

    if not item or not item.watchers:
        return

    _send_notification(client, channel_id, thread_ts, message, item.watchers[:MAX_MENTIONS])


async def notify_participants(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    message: str,
    *,
    exclude_user_id: Optional[str] = None,
) -> None:
    """Notify active thread participants (last 30 min).

    Args:
        client: Slack WebClient for posting messages
        channel_id: Channel to post in
        thread_ts: Thread to reply in
        message: Message text to send (mentions will be prepended)
        exclude_user_id: User to exclude from notifications (e.g., the sender)
    """
    from src.db import get_connection
    from src.db.participant_store import ThreadParticipantStore

    async with get_connection() as conn:
        store = ThreadParticipantStore(conn)
        participants = await store.get_active_participants(channel_id, thread_ts)

    recipients = [p.user_id for p in participants if p.user_id != exclude_user_id]

    if recipients:
        _send_notification(client, channel_id, thread_ts, message, recipients[:MAX_MENTIONS])


async def notify_user(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    message: str,
) -> None:
    """Notify a specific user with @mention.

    Args:
        client: Slack WebClient for posting messages
        channel_id: Channel to post in
        thread_ts: Thread to reply in
        user_id: User to notify
        message: Message text to send
    """
    _send_notification(client, channel_id, thread_ts, message, [user_id])


def _send_notification(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    message: str,
    user_ids: list[str],
) -> None:
    """Send notification with @mentions.

    Internal helper that formats mentions and posts to Slack.

    Args:
        client: Slack WebClient
        channel_id: Channel to post in
        thread_ts: Thread to reply in
        message: Base message text
        user_ids: Users to mention (will be limited to MAX_MENTIONS)
    """
    if not user_ids:
        return

    mentions = " ".join(format_user_mention(uid) for uid in user_ids[:MAX_MENTIONS])
    full_message = f"{mentions} {message}"

    # Apply mention limit as safety measure
    safe_message = limit_mentions(full_message, MAX_MENTIONS)

    try:
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=safe_message,
        )
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")


async def notify_owners_and_watchers(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    workitem_id: str,
    message: str,
    *,
    exclude_user_id: Optional[str] = None,
) -> None:
    """Notify both owners and watchers of a WorkItem.

    Combines owners and watchers into a single notification,
    respecting MAX_MENTIONS limit. Owners take priority.

    Args:
        client: Slack WebClient for posting messages
        channel_id: Channel to post in
        thread_ts: Thread to reply in
        workitem_id: WorkItem UUID to get recipients from
        message: Message text to send
        exclude_user_id: User to exclude (e.g., the actor who triggered this)
    """
    from src.db import get_connection
    from src.db.workitem_store import WorkItemStore

    async with get_connection() as conn:
        store = WorkItemStore(conn)
        item = await store.get(workitem_id)

    if not item:
        logger.warning(f"WorkItem not found for notification: {workitem_id}")
        return

    # Combine owners and watchers, owners first (priority)
    all_recipients = []
    seen = set()

    for user_id in (item.owners or []):
        if user_id not in seen and user_id != exclude_user_id:
            all_recipients.append(user_id)
            seen.add(user_id)

    for user_id in (item.watchers or []):
        if user_id not in seen and user_id != exclude_user_id:
            all_recipients.append(user_id)
            seen.add(user_id)

    if all_recipients:
        _send_notification(client, channel_id, thread_ts, message, all_recipients[:MAX_MENTIONS])
