"""
Slack Bot - Main entry point for Slack integration.

Initializes the Slack Bolt app and registers event handlers.
"""

import structlog
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from src.adapters.slack.handlers import SlackHandlers
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
