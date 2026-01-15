"""Slack blocks for architecture decisions (Phase 14)."""


def build_decision_blocks(
    topic: str,
    decision: str,
    channel_id: str,
    thread_ts: str,
    user_id: str,
) -> list[dict]:
    """Build Slack blocks for architecture decision post.

    Posted to channel (not thread) as permanent record of approved decisions.

    Format:
    *Architecture Decision*

    *Topic:* {topic}
    *Decision:* {decision}

    _View discussion - Decided by @user_

    Args:
        topic: What was being decided
        decision: The chosen approach (1-2 sentences)
        channel_id: Channel ID for thread link
        thread_ts: Thread timestamp for link
        user_id: User who approved the decision

    Returns:
        List of Slack block dicts for decision post
    """
    # Build thread link (removes dot from thread_ts for Slack permalink format)
    thread_link = f"https://slack.com/archives/{channel_id}/p{thread_ts.replace('.', '')}"

    return [
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
