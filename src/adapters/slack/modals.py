"""
Slack Modal Views - Configuration modals for /req-config command.

Builds Block Kit modal views for channel configuration.
"""

from typing import Any

from src.adapters.slack.config import (
    ChannelSettings,
    LLM_MODELS,
    DEFAULT_TEMPERATURE,
    DEFAULT_HUMOR,
    DEFAULT_VERBOSITY,
    DEFAULT_FORMALITY,
    DEFAULT_TECHNICAL_DEPTH,
    DEFAULT_EMOJI_USAGE,
)
from src.core.agents.prompts import (
    PRODUCT_MANAGER_PROMPT,
    SOFTWARE_ARCHITECT_PROMPT,
    GRAPH_ADMIN_PROMPT,
)


def build_main_config_modal(channel_id: str, settings: ChannelSettings | None) -> dict:
    """
    Build the main configuration modal.

    Args:
        channel_id: Slack channel ID.
        settings: Current channel settings or None.

    Returns:
        Slack modal view payload.
    """
    current = settings or ChannelSettings(channel_id=channel_id)

    # Build provider options
    provider_options = [
        {"text": {"type": "plain_text", "text": "OpenAI"}, "value": "openai"},
        {"text": {"type": "plain_text", "text": "Anthropic"}, "value": "anthropic"},
        {"text": {"type": "plain_text", "text": "Google"}, "value": "google"},
    ]

    # Get initial provider
    initial_provider = current.llm_provider or "openai"

    # Build model options for current provider
    model_options = [
        {"text": {"type": "plain_text", "text": label}, "value": model_id}
        for model_id, label in LLM_MODELS.get(initial_provider, LLM_MODELS["openai"])
    ]

    # Find initial model option
    initial_model = current.llm_model or model_options[0]["value"]

    blocks = [
        # Header
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Channel Configuration"},
        },
        {"type": "divider"},
        # Jira Section
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Jira Integration*"},
        },
        {
            "type": "input",
            "block_id": "jira_project_key",
            "element": {
                "type": "plain_text_input",
                "action_id": "jira_project_key_input",
                "placeholder": {"type": "plain_text", "text": "e.g., MARO"},
                "initial_value": current.jira_project_key,
            },
            "label": {"type": "plain_text", "text": "Jira Project Key"},
            "optional": True,
        },
        {"type": "divider"},
        # AI Model Section
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*AI Model*"},
        },
        {
            "type": "input",
            "block_id": "llm_provider",
            "dispatch_action": True,
            "element": {
                "type": "static_select",
                "action_id": "llm_provider_select",
                "placeholder": {"type": "plain_text", "text": "Select provider"},
                "options": provider_options,
                "initial_option": next(
                    (o for o in provider_options if o["value"] == initial_provider),
                    provider_options[0],
                ),
            },
            "label": {"type": "plain_text", "text": "Provider"},
        },
        {
            "type": "input",
            "block_id": "llm_model",
            "element": {
                "type": "static_select",
                "action_id": "llm_model_select",
                "placeholder": {"type": "plain_text", "text": "Select model"},
                "options": model_options,
                "initial_option": next(
                    (o for o in model_options if o["value"] == initial_model),
                    model_options[0],
                ),
            },
            "label": {"type": "plain_text", "text": "Model"},
        },
        {"type": "divider"},
        # Navigation buttons
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Additional Settings*"},
        },
        {
            "type": "actions",
            "block_id": "nav_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Personality Settings"},
                    "action_id": "open_personality_modal",
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit Prompts"},
                    "action_id": "open_prompts_modal",
                },
            ],
        },
    ]

    return {
        "type": "modal",
        "callback_id": "config_modal_submit",
        "private_metadata": channel_id,
        "title": {"type": "plain_text", "text": "MARO Configuration"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def build_personality_modal(channel_id: str, settings: ChannelSettings | None) -> dict:
    """
    Build the personality settings modal with sliders.

    Args:
        channel_id: Slack channel ID.
        settings: Current channel settings or None.

    Returns:
        Slack modal view payload.
    """
    current = settings or ChannelSettings(channel_id=channel_id)

    # Helper to build slider options (Slack doesn't have real sliders, use select)
    def slider_options(current_value: int) -> tuple[list[dict], dict]:
        options = [
            {"text": {"type": "plain_text", "text": f"{v}"}, "value": str(v)}
            for v in range(0, 101, 10)
        ]
        # Find closest option to current value
        closest = min(range(0, 101, 10), key=lambda x: abs(x - current_value))
        initial = next((o for o in options if o["value"] == str(closest)), options[5])
        return options, initial

    temp_opts, temp_init = slider_options(current.temperature)
    humor_opts, humor_init = slider_options(current.humor)
    verb_opts, verb_init = slider_options(current.verbosity)
    form_opts, form_init = slider_options(current.formality)
    tech_opts, tech_init = slider_options(current.technical_depth)
    emoji_opts, emoji_init = slider_options(current.emoji_usage)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "AI Personality Settings"},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Adjust these sliders to customize how the AI agents communicate.",
                }
            ],
        },
        {"type": "divider"},
        {
            "type": "input",
            "block_id": "temperature",
            "element": {
                "type": "static_select",
                "action_id": "temperature_select",
                "options": temp_opts,
                "initial_option": temp_init,
            },
            "label": {"type": "plain_text", "text": "Temperature (Creativity)"},
            "hint": {"type": "plain_text", "text": "0 = Predictable, 100 = Creative"},
        },
        {
            "type": "input",
            "block_id": "humor",
            "element": {
                "type": "static_select",
                "action_id": "humor_select",
                "options": humor_opts,
                "initial_option": humor_init,
            },
            "label": {"type": "plain_text", "text": "Humor"},
            "hint": {"type": "plain_text", "text": "0 = Strictly professional, 100 = Playful and witty"},
        },
        {
            "type": "input",
            "block_id": "verbosity",
            "element": {
                "type": "static_select",
                "action_id": "verbosity_select",
                "options": verb_opts,
                "initial_option": verb_init,
            },
            "label": {"type": "plain_text", "text": "Verbosity"},
            "hint": {"type": "plain_text", "text": "0 = Concise, 100 = Detailed"},
        },
        {
            "type": "input",
            "block_id": "formality",
            "element": {
                "type": "static_select",
                "action_id": "formality_select",
                "options": form_opts,
                "initial_option": form_init,
            },
            "label": {"type": "plain_text", "text": "Formality"},
            "hint": {"type": "plain_text", "text": "0 = Casual, 100 = Formal"},
        },
        {
            "type": "input",
            "block_id": "technical_depth",
            "element": {
                "type": "static_select",
                "action_id": "technical_depth_select",
                "options": tech_opts,
                "initial_option": tech_init,
            },
            "label": {"type": "plain_text", "text": "Technical Depth"},
            "hint": {"type": "plain_text", "text": "0 = Beginner-friendly, 100 = Expert-level"},
        },
        {
            "type": "input",
            "block_id": "emoji_usage",
            "element": {
                "type": "static_select",
                "action_id": "emoji_usage_select",
                "options": emoji_opts,
                "initial_option": emoji_init,
            },
            "label": {"type": "plain_text", "text": "Emoji Usage"},
            "hint": {"type": "plain_text", "text": "0 = No emojis, 100 = Frequent emojis"},
        },
    ]

    return {
        "type": "modal",
        "callback_id": "personality_modal_submit",
        "private_metadata": channel_id,
        "title": {"type": "plain_text", "text": "Personality"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def build_prompts_modal(channel_id: str, settings: ChannelSettings | None) -> dict:
    """
    Build the prompts selection modal.

    Args:
        channel_id: Slack channel ID.
        settings: Current channel settings or None.

    Returns:
        Slack modal view payload.
    """
    current = settings or ChannelSettings(channel_id=channel_id)

    def get_prompt_status(custom_prompt: str, default_prompt: str) -> str:
        if custom_prompt:
            return f"Custom ({len(custom_prompt)} chars)"
        return f"Default ({len(default_prompt)} chars)"

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Agent System Prompts"},
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Customize the system prompts for each AI agent. Leave empty to use defaults.",
                }
            ],
        },
        {"type": "divider"},
        # Product Manager
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Product Manager*\n{get_prompt_status(current.prompt_product_manager, PRODUCT_MANAGER_PROMPT)}",
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Edit"},
                "action_id": "edit_pm_prompt",
                "value": "product_manager",
            },
        },
        {"type": "divider"},
        # Software Architect
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Software Architect*\n{get_prompt_status(current.prompt_architect, SOFTWARE_ARCHITECT_PROMPT)}",
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Edit"},
                "action_id": "edit_architect_prompt",
                "value": "architect",
            },
        },
        {"type": "divider"},
        # Graph Admin
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Graph Admin*\n{get_prompt_status(current.prompt_graph_admin, GRAPH_ADMIN_PROMPT)}",
            },
            "accessory": {
                "type": "button",
                "text": {"type": "plain_text", "text": "Edit"},
                "action_id": "edit_graph_admin_prompt",
                "value": "graph_admin",
            },
        },
    ]

    return {
        "type": "modal",
        "callback_id": "prompts_modal_close",
        "private_metadata": channel_id,
        "title": {"type": "plain_text", "text": "Agent Prompts"},
        "close": {"type": "plain_text", "text": "Done"},
        "blocks": blocks,
    }


def build_prompt_editor_modal(
    channel_id: str,
    prompt_type: str,
    current_prompt: str,
    default_prompt: str,
) -> dict:
    """
    Build the prompt editor modal.

    Args:
        channel_id: Slack channel ID.
        prompt_type: Type of prompt (product_manager, architect, graph_admin).
        current_prompt: Current custom prompt or empty string.
        default_prompt: Default prompt for reset.

    Returns:
        Slack modal view payload.
    """
    titles = {
        "product_manager": "Product Manager Prompt",
        "architect": "Software Architect Prompt",
        "graph_admin": "Graph Admin Prompt",
    }

    # Use current prompt or default if none set
    prompt_value = current_prompt if current_prompt else default_prompt

    blocks = [
        {
            "type": "actions",
            "block_id": "prompt_actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Reset to Default"},
                    "action_id": "reset_prompt_to_default",
                    "value": prompt_type,
                    "style": "danger",
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Reset Prompt?"},
                        "text": {
                            "type": "mrkdwn",
                            "text": "This will replace your custom prompt with the default. Are you sure?",
                        },
                        "confirm": {"type": "plain_text", "text": "Reset"},
                        "deny": {"type": "plain_text", "text": "Cancel"},
                    },
                },
            ],
        },
        {
            "type": "input",
            "block_id": "prompt_content",
            "element": {
                "type": "plain_text_input",
                "action_id": "prompt_input",
                "multiline": True,
                "initial_value": prompt_value[:3000],  # Slack limit
                "placeholder": {"type": "plain_text", "text": "Enter system prompt..."},
            },
            "label": {"type": "plain_text", "text": "System Prompt"},
            "hint": {
                "type": "plain_text",
                "text": "This prompt defines the agent's behavior and personality.",
            },
        },
    ]

    return {
        "type": "modal",
        "callback_id": f"prompt_editor_submit_{prompt_type}",
        "private_metadata": channel_id,
        "title": {"type": "plain_text", "text": titles.get(prompt_type, "Edit Prompt")[:24]},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def get_default_prompt(prompt_type: str) -> str:
    """Get the default prompt for a given prompt type."""
    defaults = {
        "product_manager": PRODUCT_MANAGER_PROMPT,
        "architect": SOFTWARE_ARCHITECT_PROMPT,
        "graph_admin": GRAPH_ADMIN_PROMPT,
    }
    return defaults.get(prompt_type, "")
