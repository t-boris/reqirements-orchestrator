"""Review-related blocks including patch mode UI.

Provides block builders for:
- Patch review output with version indicator
- Full synthesis output
- "Show full architecture" and "Approve & Post Decision" buttons
- Review response with artifact action buttons (Phase 25)
"""


def build_review_response_blocks(
    review_text: str,
    persona: str,
    topic: str | None = None,
    artifact_id: str | None = None,
) -> list[dict]:
    """Build Slack blocks for review response with artifact buttons.

    Phase 25: Reviews are now stored as persistent artifacts. This adds
    buttons to approve/save the artifact or turn it into a work item.

    Args:
        review_text: The full review content
        persona: Persona name that performed review
        topic: Review topic (optional)
        artifact_id: UUID of the stored artifact (optional)

    Returns:
        List of Slack blocks for review response
    """
    blocks = [
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f":memo: *{persona}* | {topic or 'Review'}",
                },
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": review_text[:3000],  # Slack text limit
            },
        },
    ]

    # Add action buttons if we have an artifact_id
    if artifact_id:
        buttons = [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve & Save"},
                "action_id": "review_approve",
                "style": "primary",
                "value": artifact_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Turn into Work Item"},
                "action_id": "review_to_workitem",
                "value": artifact_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Dismiss"},
                "action_id": "review_dismiss",
            },
        ]

        blocks.append({"type": "divider"})
        blocks.append({
            "type": "actions",
            "elements": buttons,
        })

    return blocks


def build_patch_review_blocks(
    patch_content: str,
    version: int,
    topic: str,
) -> list[dict]:
    """Build blocks for patch review output.

    Shows patch with "Show full architecture" button.

    Args:
        patch_content: The patch content (4 sections, max 12 bullets)
        version: Current version number for tracking
        topic: Review topic for button value

    Returns:
        List of Slack blocks for patch review
    """
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"Architecture Update (v{version})",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": patch_content,
            },
        },
        {
            "type": "divider",
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Show Full Architecture"},
                    "action_id": "review_show_full",
                    "value": f"topic:{topic}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve & Post Decision"},
                    "action_id": "review_approve_decision",
                    "style": "primary",
                },
            ],
        },
    ]


def build_full_synthesis_blocks(
    full_content: str,
    topic: str,
    persona: str,
) -> list[dict]:
    """Build blocks for full synthesis output.

    Shows complete architecture review with approve/ticket options.

    Args:
        full_content: The full synthesis content
        topic: Review topic
        persona: Persona that performed review (architect, security, pm)

    Returns:
        List of Slack blocks for full synthesis
    """
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Complete Architecture Review",
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*{persona.title()} Review* | Topic: {topic}",
                },
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": full_content,
            },
        },
        {
            "type": "divider",
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve & Post Decision"},
                    "action_id": "review_approve_decision",
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Turn into Ticket"},
                    "action_id": "review_to_ticket",
                },
            ],
        },
    ]
