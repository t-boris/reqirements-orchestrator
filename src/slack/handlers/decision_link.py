"""Decision linking handlers for connecting approved decisions to Jira.

Handles button actions for linking decisions to Jira tickets.
"""
import json
import logging
from datetime import datetime, timezone

from slack_sdk.web import WebClient

from src.slack.handlers.core import _run_async

logger = logging.getLogger(__name__)


def handle_link_decision(ack, body, client: WebClient):
    """Handle decision link button click (link_decision_{key}).

    Links the decision to the selected Jira issue.
    Pattern: Sync wrapper with immediate ack, delegates to async.
    """
    ack()
    _run_async(_handle_link_decision_async(body, client))


async def _handle_link_decision_async(body, client: WebClient):
    """Async handler for linking decision to Jira."""
    from src.slack.decision_linker import DecisionLinker

    # Extract data from button
    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse link_decision button value: {button_value}")
        return

    issue_key = data.get("key", "")
    topic = data.get("topic", "")
    decision = data.get("decision", "")
    user_id = data.get("user_id", body["user"]["id"])

    message = body.get("message", {})
    thread_ts = message.get("thread_ts") or message.get("ts")
    channel_id = body["channel"]["id"]

    logger.info(
        "Decision link button clicked",
        extra={
            "issue_key": issue_key,
            "channel_id": channel_id,
            "user_id": user_id,
        }
    )

    try:
        linker = DecisionLinker()

        # Build Slack thread link
        slack_link = f"https://slack.com/archives/{channel_id}/p{thread_ts.replace('.', '')}"

        # Format and apply decision
        timestamp = datetime.now(timezone.utc).isoformat()
        formatted_decision = linker.format_decision_for_jira(
            topic=topic,
            decision=decision,
            approver=f"<@{user_id}>",
            timestamp=timestamp,
            slack_link=slack_link,
        )

        success = await linker.apply_decision_to_issue(
            issue_key,
            formatted_decision,
            mode="add_comment",
            add_label=True,
        )

        await linker.close()

        if success:
            # Update the original message to show success
            client.chat_update(
                channel=channel_id,
                ts=message.get("ts"),
                text=f"Decision linked to *{issue_key}*",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f":white_check_mark: Decision linked to *{issue_key}*"
                        }
                    }
                ]
            )
        else:
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"Failed to link decision to *{issue_key}*. Please try manually.",
            )

    except Exception as e:
        logger.error(f"Failed to link decision: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"Failed to link decision to *{issue_key}*: {str(e)}",
        )


def handle_skip_decision_link(ack, body, client: WebClient):
    """Handle skip decision link button click.

    Dismisses the link prompt without linking.
    """
    ack()

    message = body.get("message", {})
    channel_id = body["channel"]["id"]

    # Update message to show skipped
    client.chat_update(
        channel=channel_id,
        ts=message.get("ts"),
        text="Decision link skipped",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "_Decision link skipped_"
                }
            }
        ]
    )

    logger.info("Decision link skipped")


def handle_decision_link_prompt(ack, body, client: WebClient):
    """Handle "Link to Jira Ticket" button on posted decisions.

    Shows issue selection UI for retroactive linking.
    Pattern: Sync wrapper with immediate ack, delegates to async.
    """
    ack()
    _run_async(_handle_decision_link_prompt_async(body, client))


async def _handle_decision_link_prompt_async(body, client: WebClient):
    """Async handler for decision link prompt."""
    from src.slack.decision_linker import DecisionLinker
    from src.jira.client import JiraService
    from src.config.settings import get_settings

    # Extract data from button
    action = body["actions"][0]
    button_value = action.get("value", "{}")

    try:
        data = json.loads(button_value)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse decision_link_prompt button value: {button_value}")
        return

    topic = data.get("topic", "")
    decision = data.get("decision", "")
    channel_id = data.get("channel_id", body["channel"]["id"])
    thread_ts = data.get("thread_ts", "")
    user_id = data.get("user_id", body["user"]["id"])

    message = body.get("message", {})
    msg_ts = message.get("ts")

    logger.info(
        "Decision link prompt button clicked",
        extra={
            "channel_id": channel_id,
            "topic": topic,
        }
    )

    try:
        linker = DecisionLinker()

        # Find related issues
        related_issues = await linker.find_related_issues(
            decision_topic=topic,
            decision_text=decision,
            channel_id=channel_id,
        )

        await linker.close()

        if not related_issues:
            # No related issues - show manual input prompt
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=msg_ts,
                text="No related Jira tickets found. You can link manually by mentioning the ticket key (e.g., SCRUM-123) in a reply to this decision.",
            )
            return

        # Build selection UI similar to _prompt_decision_link
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*Link to Jira ticket:*\n_{topic}_"}
            },
            {"type": "divider"},
        ]

        # Fetch issue summaries for context
        try:
            settings = get_settings()
            jira = JiraService(settings)

            for key in related_issues[:5]:
                try:
                    issue = await jira.get_issue(key)
                    summary = issue.summary[:60] + "..." if len(issue.summary) > 60 else issue.summary
                except Exception:
                    summary = "(Could not fetch summary)"

                button_value = json.dumps({
                    "key": key,
                    "topic": topic[:100],
                    "decision": decision[:500],
                    "user_id": user_id,
                })

                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{key}*: {summary}"},
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Link"},
                        "action_id": f"link_decision_{key}",
                        "value": button_value,
                    }
                })

            await jira.close()

        except Exception as e:
            logger.warning(f"Failed to fetch issue summaries: {e}")
            # Show keys without summaries
            for key in related_issues[:5]:
                button_value = json.dumps({
                    "key": key,
                    "topic": topic[:100],
                    "decision": decision[:500],
                    "user_id": user_id,
                })
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": f"*{key}*"},
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Link"},
                        "action_id": f"link_decision_{key}",
                        "value": button_value,
                    }
                })

        # Add cancel button
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Cancel"},
                    "action_id": "skip_decision_link"
                }
            ]
        })

        # Post as reply in thread (if decision was in channel, this creates thread)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=msg_ts,
            blocks=blocks,
            text="Link to Jira ticket?",
        )

    except Exception as e:
        logger.error(f"Failed to show decision link prompt: {e}", exc_info=True)
        client.chat_postMessage(
            channel=channel_id,
            thread_ts=msg_ts,
            text="Failed to load related Jira tickets. Please try again.",
        )
