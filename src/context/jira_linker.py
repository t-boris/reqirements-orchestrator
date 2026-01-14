"""Jira linkage for channel context - connects threads to Jira issues."""
import logging
from dataclasses import dataclass
from typing import Optional

from slack_sdk import WebClient

from src.jira.client import JiraService
from src.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ThreadJiraLink:
    """Link between Slack thread and Jira issue."""
    channel_id: str
    thread_ts: str
    epic_key: Optional[str] = None
    ticket_key: Optional[str] = None
    pin_ts: Optional[str] = None  # Timestamp of pinned message


class JiraLinker:
    """Manages Slack thread <-> Jira issue linkage.

    Handles:
    - Pinning summary message in thread on epic bind
    - Updating pin when ticket created
    - Adding Slack permalink to Jira description
    """

    def __init__(self, slack_client: WebClient, jira_service: JiraService) -> None:
        self._slack = slack_client
        self._jira = jira_service

    async def on_epic_bound(
        self,
        channel_id: str,
        thread_ts: str,
        epic_key: str,
        epic_summary: str,
    ) -> ThreadJiraLink:
        """Called when thread is bound to an epic.

        Posts and pins a summary message: "Epic: PROJ-123 | Epic Title"

        Args:
            channel_id: Slack channel.
            thread_ts: Thread root timestamp.
            epic_key: Jira epic key (e.g., PROJ-123).
            epic_summary: Epic summary/title.

        Returns:
            ThreadJiraLink with pin_ts set.
        """
        settings = get_settings()
        epic_url = f"{settings.jira_url}/browse/{epic_key}"

        # Post summary message
        result = self._slack.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f":dart: *Epic:* <{epic_url}|{epic_key}> - {epic_summary}",
        )
        message_ts = result["ts"]

        # Pin the message
        try:
            self._slack.pins_add(channel=channel_id, timestamp=message_ts)
        except Exception as e:
            logger.warning(f"Failed to pin epic message: {e}")

        return ThreadJiraLink(
            channel_id=channel_id,
            thread_ts=thread_ts,
            epic_key=epic_key,
            pin_ts=message_ts,
        )

    async def on_ticket_created(
        self,
        channel_id: str,
        thread_ts: str,
        ticket_key: str,
        ticket_url: str,
        existing_pin_ts: Optional[str] = None,
    ) -> ThreadJiraLink:
        """Called when ticket is created from thread.

        Updates existing pin or creates new one with ticket link.

        Args:
            channel_id: Slack channel.
            thread_ts: Thread root timestamp.
            ticket_key: Created Jira ticket key.
            ticket_url: URL to the ticket.
            existing_pin_ts: Existing pinned message to update.

        Returns:
            ThreadJiraLink with updated info.
        """
        if existing_pin_ts:
            # Update existing message
            try:
                self._slack.chat_update(
                    channel=channel_id,
                    ts=existing_pin_ts,
                    text=f":white_check_mark: *Ticket Created:* <{ticket_url}|{ticket_key}>",
                )
            except Exception as e:
                logger.warning(f"Failed to update pin: {e}, posting new message")
                existing_pin_ts = None

        if not existing_pin_ts:
            # Post new pinned message
            result = self._slack.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f":white_check_mark: *Ticket Created:* <{ticket_url}|{ticket_key}>",
            )
            message_ts = result["ts"]

            try:
                self._slack.pins_add(channel=channel_id, timestamp=message_ts)
            except Exception as e:
                logger.warning(f"Failed to pin ticket message: {e}")

            existing_pin_ts = message_ts

        return ThreadJiraLink(
            channel_id=channel_id,
            thread_ts=thread_ts,
            ticket_key=ticket_key,
            pin_ts=existing_pin_ts,
        )

    def get_thread_permalink(self, channel_id: str, thread_ts: str) -> str:
        """Get Slack permalink for a thread.

        Used when creating Jira ticket to store link back to Slack.
        """
        try:
            result = self._slack.chat_getPermalink(
                channel=channel_id,
                message_ts=thread_ts,
            )
            return result["permalink"]
        except Exception as e:
            logger.warning(f"Failed to get permalink: {e}")
            return ""
