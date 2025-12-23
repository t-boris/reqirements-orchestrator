"""
Slack Handler Helpers.

Helper functions for Slack handlers.
"""

from typing import Any

import structlog

from src.slack.channel_config_store import (
    ChannelConfig,
    get_available_models,
)
from src.slack.knowledge_store import get_knowledge_files

logger = structlog.get_logger()

# Helper Functions
# =============================================================================


async def _get_bot_user_id(client) -> str:
    """Get the bot's user ID."""
    response = await client.auth_test()
    return response.get("user_id", "")


async def _process_attachments(event: dict, client) -> list[dict[str, Any]]:
    """
    Process and extract content from message attachments.

    Args:
        event: Slack message event.
        client: Slack client.

    Returns:
        List of processed attachment data.
    """
    attachments = []

    # Process files
    files = event.get("files", [])
    for file in files:
        attachment = {
            "type": "file",
            "name": file.get("name", ""),
            "mimetype": file.get("mimetype", ""),
            "url": file.get("url_private", ""),
        }

        # Try to read text file content
        if file.get("mimetype", "").startswith("text/"):
            try:
                # Download file content
                response = await client.files_info(file=file["id"])
                content = response.get("content", "")
                attachment["content"] = content[:10000]  # Limit size
            except Exception as e:
                logger.warning("file_download_failed", file=file["name"], error=str(e))

        attachments.append(attachment)

    return attachments


def _format_status(state: dict) -> str:
    """Format state for status display."""
    parts = [
        "*Current State*",
        f"Intent: `{state.get('intent', 'unknown')}`",
        f"Confidence: `{state.get('intent_confidence', 0):.0%}`",
        f"Active Persona: `{state.get('active_persona') or 'Main Bot'}`",
    ]

    if state.get("draft"):
        draft = state["draft"]
        parts.append(f"\n*Draft*")
        parts.append(f"Title: {draft.get('title', 'Untitled')}")
        parts.append(f"Type: {draft.get('issue_type', 'Unknown')}")

    if state.get("jira_issue_key"):
        parts.append(f"\n*Jira*: {state['jira_issue_key']}")

    if state.get("awaiting_human"):
        parts.append("\n_Awaiting human approval_")

    return "\n".join(parts)


def _build_config_modal(config: ChannelConfig, knowledge_files: list) -> dict:
    """Build the channel configuration modal with current values."""

    # Build model options
    models = get_available_models()
    model_options = [
        {"text": {"type": "plain_text", "text": m["label"]}, "value": m["value"]}
        for m in models
    ]

    # Find current model option
    current_model_option = next(
        (opt for opt in model_options if opt["value"] == config.default_model),
        model_options[0]  # Default to first option
    )

    # Issue type options
    issue_types = ["Story", "Task", "Bug", "Epic"]
    issue_type_options = [
        {"text": {"type": "plain_text", "text": t}, "value": t}
        for t in issue_types
    ]
    current_issue_option = next(
        (opt for opt in issue_type_options if opt["value"] == config.jira_default_issue_type),
        issue_type_options[0]
    )

    # Get inline knowledge for personas
    architect_inline = config.persona_knowledge.get("architect", {}).get("inline", "")
    pm_inline = config.persona_knowledge.get("product_manager", {}).get("inline", "")
    security_inline = config.persona_knowledge.get("security_analyst", {}).get("inline", "")

    # Convert personality values to 0-10 scale
    humor_val = str(int(config.personality.humor * 10))
    formality_val = str(int(config.personality.formality * 10))
    emoji_val = str(int(config.personality.emoji_usage * 10))
    verbosity_val = str(int(config.personality.verbosity * 10))

    return {
        "type": "modal",
        "callback_id": "config_modal",
        "private_metadata": config.channel_id,
        "title": {"type": "plain_text", "text": "Channel Config"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            # ===== JIRA SETTINGS =====
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Jira Settings"},
            },
            {
                "type": "input",
                "block_id": "project_key",
                "optional": True,
                "label": {"type": "plain_text", "text": "Jira Project Key"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "project_key_input",
                    "placeholder": {"type": "plain_text", "text": "e.g., MARO"},
                    "initial_value": config.jira_project_key or "",
                },
            },
            {
                "type": "input",
                "block_id": "default_issue_type",
                "label": {"type": "plain_text", "text": "Default Issue Type"},
                "element": {
                    "type": "static_select",
                    "action_id": "issue_type_select",
                    "options": issue_type_options,
                    "initial_option": current_issue_option,
                },
            },

            # ===== LLM MODEL =====
            {"type": "divider"},
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "LLM Model"},
            },
            {
                "type": "input",
                "block_id": "llm_model",
                "label": {"type": "plain_text", "text": "Default Model"},
                "element": {
                    "type": "static_select",
                    "action_id": "model_select",
                    "options": model_options,
                    "initial_option": current_model_option,
                },
            },

            # ===== BOT PERSONALITY =====
            {"type": "divider"},
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Bot Personality (0-10)"},
            },
            {
                "type": "input",
                "block_id": "personality_humor",
                "label": {"type": "plain_text", "text": "Humor Level"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "humor_input",
                    "initial_value": humor_val,
                    "placeholder": {"type": "plain_text", "text": "0-10"},
                },
                "hint": {"type": "plain_text", "text": "0 = Serious, 10 = Very humorous"},
            },
            {
                "type": "input",
                "block_id": "personality_formality",
                "label": {"type": "plain_text", "text": "Formality Level"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "formality_input",
                    "initial_value": formality_val,
                    "placeholder": {"type": "plain_text", "text": "0-10"},
                },
                "hint": {"type": "plain_text", "text": "0 = Casual, 10 = Very formal"},
            },
            {
                "type": "input",
                "block_id": "personality_emoji",
                "label": {"type": "plain_text", "text": "Emoji Usage"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "emoji_input",
                    "initial_value": emoji_val,
                    "placeholder": {"type": "plain_text", "text": "0-10"},
                },
                "hint": {"type": "plain_text", "text": "0 = No emojis, 10 = Lots of emojis"},
            },
            {
                "type": "input",
                "block_id": "personality_verbosity",
                "label": {"type": "plain_text", "text": "Verbosity"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "verbosity_input",
                    "initial_value": verbosity_val,
                    "placeholder": {"type": "plain_text", "text": "0-10"},
                },
                "hint": {"type": "plain_text", "text": "0 = Concise, 10 = Detailed"},
            },

            # ===== PERSONA KNOWLEDGE =====
            {"type": "divider"},
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "Custom Knowledge"},
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": "Add custom context for each persona. Use `/req-upload` to add files."},
                ],
            },
            {
                "type": "input",
                "block_id": "architect_knowledge",
                "optional": True,
                "label": {"type": "plain_text", "text": "Architect Knowledge"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "architect_knowledge_input",
                    "multiline": True,
                    "initial_value": architect_inline,
                    "placeholder": {"type": "plain_text", "text": "Custom architecture guidelines..."},
                },
            },
            {
                "type": "input",
                "block_id": "pm_knowledge",
                "optional": True,
                "label": {"type": "plain_text", "text": "Product Manager Knowledge"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "pm_knowledge_input",
                    "multiline": True,
                    "initial_value": pm_inline,
                    "placeholder": {"type": "plain_text", "text": "Product requirements, user story formats..."},
                },
            },
            {
                "type": "input",
                "block_id": "security_knowledge",
                "optional": True,
                "label": {"type": "plain_text", "text": "Security Analyst Knowledge"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "security_knowledge_input",
                    "multiline": True,
                    "initial_value": security_inline,
                    "placeholder": {"type": "plain_text", "text": "Security policies, compliance requirements..."},
                },
            },
        ],
    }


async def _handle_approval_list(client, channel_id: str, user_id: str) -> None:
    """Handle /req-approve list command."""
    from src.slack.approval import get_permanent_approvals

    approvals = await get_permanent_approvals(channel_id)

    if not approvals:
        text = "No permanent approvals configured for this channel."
    else:
        lines = ["*Permanent Approvals*\n"]
        for i, approval in enumerate(approvals, 1):
            lines.append(f"{i}. `{approval.get('pattern', '')}` - Created by <@{approval.get('user_id', '')}>")
        text = "\n".join(lines)

    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=text,
    )


async def _handle_approval_delete(client, channel_id: str, user_id: str, approval_id: str) -> None:
    """Handle /req-approve delete command."""
    from src.slack.approval import delete_permanent_approval

    success = await delete_permanent_approval(channel_id, approval_id)

    if success:
        text = f"Approval `{approval_id}` has been deleted."
    else:
        text = f"Approval `{approval_id}` not found."

    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=text,
    )
