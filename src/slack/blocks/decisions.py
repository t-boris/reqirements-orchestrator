"""Slack blocks for architecture decisions (Phase 14, 21-05)."""
import json


def build_decision_blocks(
    topic: str,
    decision: str,
    channel_id: str,
    thread_ts: str,
    user_id: str,
    show_link_button: bool = True,
) -> list[dict]:
    """Build Slack blocks for architecture decision post.

    Posted to channel (not thread) as permanent record of approved decisions.

    Format:
    *Architecture Decision*

    *Topic:* {topic}
    *Decision:* {decision}

    _View discussion - Decided by @user_

    [Link to Jira Ticket]  (optional)

    Args:
        topic: What was being decided
        decision: The chosen approach (1-2 sentences)
        channel_id: Channel ID for thread link
        thread_ts: Thread timestamp for link
        user_id: User who approved the decision
        show_link_button: Whether to show "Link to Jira" button (default True)

    Returns:
        List of Slack block dicts for decision post
    """
    # Build thread link (removes dot from thread_ts for Slack permalink format)
    thread_link = f"https://slack.com/archives/{channel_id}/p{thread_ts.replace('.', '')}"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":triangular_ruler: *Architecture Decision*\n\n*Topic:* {topic}\n\n*Decision:* {decision}"
            }
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"<{thread_link}|View discussion> - Decided by <@{user_id}>"
                }
            ]
        }
    ]

    # Add "Link to Jira Ticket" button for retroactive linking
    if show_link_button:
        button_value = json.dumps({
            "topic": topic[:100],
            "decision": decision[:500],
            "channel_id": channel_id,
            "thread_ts": thread_ts,
            "user_id": user_id,
        })

        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Link to Jira Ticket"},
                    "action_id": "decision_link_prompt",
                    "value": button_value,
                }
            ]
        })

    return blocks
