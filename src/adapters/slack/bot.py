"""
Slack Bot - Main entry point for Slack integration.

Initializes the Slack Bolt app and registers event handlers.
"""

import structlog
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from src.adapters.slack.handlers import SlackHandlers
from src.adapters.slack.modals import (
    build_main_config_modal,
    build_personality_modal,
    build_prompts_modal,
    build_prompt_editor_modal,
    get_default_prompt,
)
from src.config.settings import Settings

logger = structlog.get_logger()


class SlackBot:
    """
    Slack Bot using Bolt SDK.

    Handles:
    - Message events (for natural language processing)
    - Slash commands (/req-status, /req-nfr, /req-clean, /req-reset)
    - App mentions
    """

    def __init__(
        self,
        settings: Settings,
        handlers: SlackHandlers,
    ) -> None:
        """
        Initialize Slack bot.

        Args:
            settings: Application settings.
            handlers: Message and command handlers.
        """
        self._settings = settings
        self._handlers = handlers

        # Initialize Bolt app
        self._app = AsyncApp(
            token=settings.slack_bot_token,
            signing_secret=settings.slack_signing_secret,
        )

        # Register handlers
        self._register_handlers()

        logger.info("slack_bot_initialized")

    def _register_handlers(self) -> None:
        """Register all event handlers with the Bolt app."""

        # Message handler - processes all messages in channels where bot is present
        @self._app.event("message")
        async def handle_message(event: dict, say, client) -> None:
            """Handle incoming messages."""
            # Ignore bot messages and message edits
            if event.get("bot_id") or event.get("subtype"):
                return

            await self._handlers.handle_message(
                channel_id=event["channel"],
                user_id=event["user"],
                text=event.get("text", ""),
                thread_ts=event.get("thread_ts"),
                say=say,
                client=client,
            )

        # App mention handler - @MARO mentions
        @self._app.event("app_mention")
        async def handle_mention(event: dict, say, client) -> None:
            """Handle @mentions of the bot."""
            await self._handlers.handle_message(
                channel_id=event["channel"],
                user_id=event["user"],
                text=event.get("text", ""),
                thread_ts=event.get("thread_ts") or event.get("ts"),
                say=say,
                client=client,
            )

        # /req-status command
        @self._app.command("/req-status")
        async def handle_status(ack, command, say) -> None:
            """Handle /req-status command."""
            await ack()
            await self._handlers.handle_status_command(
                channel_id=command["channel_id"],
                user_id=command["user_id"],
                say=say,
            )

        # /req-nfr command
        @self._app.command("/req-nfr")
        async def handle_nfr(ack, command, say) -> None:
            """Handle /req-nfr command."""
            await ack()
            await self._handlers.handle_nfr_command(
                channel_id=command["channel_id"],
                user_id=command["user_id"],
                text=command.get("text", ""),
                say=say,
            )

        # /req-clean command
        @self._app.command("/req-clean")
        async def handle_clean(ack, command, say) -> None:
            """Handle /req-clean command."""
            await ack()
            await self._handlers.handle_clean_command(
                channel_id=command["channel_id"],
                user_id=command["user_id"],
                say=say,
            )

        # /req-reset command
        @self._app.command("/req-reset")
        async def handle_reset(ack, command, say) -> None:
            """Handle /req-reset command."""
            await ack()
            await self._handlers.handle_reset_command(
                channel_id=command["channel_id"],
                user_id=command["user_id"],
                say=say,
            )

        # /req-config command - opens configuration modal
        @self._app.command("/req-config")
        async def handle_config(ack, command, client) -> None:
            """Handle /req-config command - opens config modal."""
            await ack()
            channel_id = command["channel_id"]
            settings = self._handlers.get_channel_settings(channel_id)

            await client.views_open(
                trigger_id=command["trigger_id"],
                view=build_main_config_modal(channel_id, settings),
            )

        # Modal submission handlers

        @self._app.view("config_modal_submit")
        async def handle_config_submit(ack, body, view, client) -> None:
            """Handle main config modal submission."""
            await ack()
            channel_id = view["private_metadata"]
            values = view["state"]["values"]

            updates = {
                "jira_project_key": values["jira_project_key"]["jira_project_key_input"].get("value", "") or "",
                "llm_provider": values["llm_provider"]["llm_provider_select"]["selected_option"]["value"],
                "llm_model": values["llm_model"]["llm_model_select"]["selected_option"]["value"],
            }

            self._handlers.update_channel_settings(channel_id, **updates)
            logger.info("config_updated", channel_id=channel_id, updates=updates)

            # Send confirmation message
            provider_display = updates["llm_provider"].capitalize()
            model_display = updates["llm_model"]
            jira_display = updates["jira_project_key"] or "_not configured_"

            await client.chat_postMessage(
                channel=channel_id,
                text=f"Configuration updated: Provider={provider_display}, Model={model_display}",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Configuration Updated*",
                        },
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Provider:* {provider_display}"},
                            {"type": "mrkdwn", "text": f"*Model:* {model_display}"},
                            {"type": "mrkdwn", "text": f"*Jira Project:* {jira_display}"},
                        ],
                    },
                ],
            )

        @self._app.view("personality_modal_submit")
        async def handle_personality_submit(ack, body, view, client) -> None:
            """Handle personality modal submission."""
            await ack()
            channel_id = view["private_metadata"]
            values = view["state"]["values"]

            updates = {
                "temperature": int(values["temperature"]["temperature_select"]["selected_option"]["value"]),
                "humor": int(values["humor"]["humor_select"]["selected_option"]["value"]),
                "verbosity": int(values["verbosity"]["verbosity_select"]["selected_option"]["value"]),
                "formality": int(values["formality"]["formality_select"]["selected_option"]["value"]),
                "technical_depth": int(values["technical_depth"]["technical_depth_select"]["selected_option"]["value"]),
                "emoji_usage": int(values["emoji_usage"]["emoji_usage_select"]["selected_option"]["value"]),
            }

            self._handlers.update_channel_settings(channel_id, **updates)
            logger.info("personality_updated", channel_id=channel_id, updates=updates)

            # Send confirmation message
            await client.chat_postMessage(
                channel=channel_id,
                text="Personality settings updated",
                blocks=[
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": "*Personality Settings Updated*",
                        },
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Temperature:* {updates['temperature']}%"},
                            {"type": "mrkdwn", "text": f"*Humor:* {updates['humor']}%"},
                            {"type": "mrkdwn", "text": f"*Verbosity:* {updates['verbosity']}%"},
                            {"type": "mrkdwn", "text": f"*Formality:* {updates['formality']}%"},
                            {"type": "mrkdwn", "text": f"*Technical Depth:* {updates['technical_depth']}%"},
                            {"type": "mrkdwn", "text": f"*Emoji Usage:* {updates['emoji_usage']}%"},
                        ],
                    },
                ],
            )

        # Helper function for prompt submission
        async def _handle_prompt_submit(ack, view, client, prompt_type: str) -> None:
            await ack()
            channel_id = view["private_metadata"]
            values = view["state"]["values"]
            prompt_content = values["prompt_content"]["prompt_input"].get("value", "") or ""

            field_map = {
                "product_manager": "prompt_product_manager",
                "architect": "prompt_architect",
                "graph_admin": "prompt_graph_admin",
            }

            display_names = {
                "product_manager": "Product Manager",
                "architect": "Software Architect",
                "graph_admin": "Graph Admin",
            }

            field_name = field_map.get(prompt_type)
            if field_name:
                self._handlers.update_channel_settings(channel_id, **{field_name: prompt_content})
                logger.info("prompt_updated", channel_id=channel_id, prompt_type=prompt_type)

                # Send confirmation message
                display_name = display_names.get(prompt_type, prompt_type)
                status = "custom prompt saved" if prompt_content else "reset to default"
                await client.chat_postMessage(
                    channel=channel_id,
                    text=f"{display_name} prompt updated",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"*{display_name} Prompt Updated*\n{status} ({len(prompt_content)} chars)",
                            },
                        },
                    ],
                )

        @self._app.view("prompt_editor_submit_product_manager")
        async def handle_pm_prompt_submit(ack, body, view, client) -> None:
            await _handle_prompt_submit(ack, view, client, "product_manager")

        @self._app.view("prompt_editor_submit_architect")
        async def handle_arch_prompt_submit(ack, body, view, client) -> None:
            await _handle_prompt_submit(ack, view, client, "architect")

        @self._app.view("prompt_editor_submit_graph_admin")
        async def handle_admin_prompt_submit(ack, body, view, client) -> None:
            await _handle_prompt_submit(ack, view, client, "graph_admin")

        # Action handlers for navigation buttons

        @self._app.action("open_personality_modal")
        async def handle_open_personality(ack, body, client) -> None:
            """Open personality settings modal."""
            await ack()
            channel_id = body["view"]["private_metadata"]
            settings = self._handlers.get_channel_settings(channel_id)

            await client.views_push(
                trigger_id=body["trigger_id"],
                view=build_personality_modal(channel_id, settings),
            )

        @self._app.action("open_prompts_modal")
        async def handle_open_prompts(ack, body, client) -> None:
            """Open prompts selection modal."""
            await ack()
            channel_id = body["view"]["private_metadata"]
            settings = self._handlers.get_channel_settings(channel_id)

            await client.views_push(
                trigger_id=body["trigger_id"],
                view=build_prompts_modal(channel_id, settings),
            )

        @self._app.action("edit_pm_prompt")
        async def handle_edit_pm_prompt(ack, body, client) -> None:
            """Open Product Manager prompt editor."""
            await ack()
            channel_id = body["view"]["private_metadata"]
            settings = self._handlers.get_channel_settings(channel_id)
            current = settings.prompt_product_manager if settings else ""

            await client.views_push(
                trigger_id=body["trigger_id"],
                view=build_prompt_editor_modal(
                    channel_id, "product_manager", current, get_default_prompt("product_manager")
                ),
            )

        @self._app.action("edit_architect_prompt")
        async def handle_edit_architect_prompt(ack, body, client) -> None:
            """Open Architect prompt editor."""
            await ack()
            channel_id = body["view"]["private_metadata"]
            settings = self._handlers.get_channel_settings(channel_id)
            current = settings.prompt_architect if settings else ""

            await client.views_push(
                trigger_id=body["trigger_id"],
                view=build_prompt_editor_modal(
                    channel_id, "architect", current, get_default_prompt("architect")
                ),
            )

        @self._app.action("edit_graph_admin_prompt")
        async def handle_edit_graph_admin_prompt(ack, body, client) -> None:
            """Open Graph Admin prompt editor."""
            await ack()
            channel_id = body["view"]["private_metadata"]
            settings = self._handlers.get_channel_settings(channel_id)
            current = settings.prompt_graph_admin if settings else ""

            await client.views_push(
                trigger_id=body["trigger_id"],
                view=build_prompt_editor_modal(
                    channel_id, "graph_admin", current, get_default_prompt("graph_admin")
                ),
            )

        @self._app.action("reset_prompt_to_default")
        async def handle_reset_prompt(ack, body, client) -> None:
            """Reset prompt to default."""
            await ack()
            channel_id = body["view"]["private_metadata"]
            prompt_type = body["actions"][0]["value"]

            # Map prompt type to field name
            field_map = {
                "product_manager": "prompt_product_manager",
                "architect": "prompt_architect",
                "graph_admin": "prompt_graph_admin",
            }

            field_name = field_map.get(prompt_type)
            if field_name:
                # Set to empty string to use default
                self._handlers.update_channel_settings(channel_id, **{field_name: ""})
                logger.info("prompt_reset_to_default", channel_id=channel_id, prompt_type=prompt_type)

            # Update the modal with the default prompt
            default_prompt = get_default_prompt(prompt_type)
            await client.views_update(
                view_id=body["view"]["id"],
                view=build_prompt_editor_modal(channel_id, prompt_type, "", default_prompt),
            )

        # Handle select changes (for dynamic model dropdown based on provider)
        @self._app.action("llm_provider_select")
        async def handle_provider_change(ack, body, client) -> None:
            """Handle provider selection change - update model options dynamically."""
            await ack()

            # Extract current values from the view state
            view = body["view"]
            channel_id = view["private_metadata"]
            values = view["state"]["values"]

            # Get the newly selected provider
            new_provider = body["actions"][0]["selected_option"]["value"]

            # Get current Jira project key value
            jira_key = values.get("jira_project_key", {}).get("jira_project_key_input", {}).get("value", "") or ""

            # Build updated settings with new provider
            from src.adapters.slack.config import ChannelSettings
            updated_settings = ChannelSettings(
                channel_id=channel_id,
                jira_project_key=jira_key,
                llm_provider=new_provider,
                llm_model="",  # Reset model to first option of new provider
            )

            # Update the modal with new model options
            await client.views_update(
                view_id=view["id"],
                view=build_main_config_modal(channel_id, updated_settings),
            )

        @self._app.action("llm_model_select")
        async def handle_model_change(ack, body, client) -> None:
            """Handle model selection change."""
            await ack()
            # Just acknowledge, actual save happens on submit

    @property
    def app(self) -> AsyncApp:
        """Get the Bolt app instance."""
        return self._app

    async def start_socket_mode(self) -> None:
        """Start the bot in Socket Mode (for development)."""
        handler = AsyncSocketModeHandler(self._app, self._settings.slack_app_token)
        logger.info("starting_socket_mode")
        await handler.start_async()

    async def get_bot_user_id(self) -> str:
        """Get the bot's user ID."""
        response = await self._app.client.auth_test()
        return response["user_id"]
