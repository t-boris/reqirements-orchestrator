"""Slash command handlers.

Ref: RESEARCH.md - Pattern 4: Slash Command Handler
Ref: CONTEXT.md - Slash Commands (Skeleton Only)
"""
import logging
from slack_bolt.async_app import AsyncApp

logger = logging.getLogger(__name__)

# Commands from CONTEXT.md - only /maro help implemented now
AVAILABLE_COMMANDS = {
    "help": "Show available commands",
    "status": "Show channel status (coming soon)",
    "sync": "Check Jira sync status (coming soon)",
    "decisions": "List active decisions (coming soon)",
    "entities": "List all entities (coming soon)",
    "config": "Channel configuration (coming soon)",
}


def register_command_handlers(app: AsyncApp) -> None:
    """Register slash command handlers on the Bolt app."""

    @app.command("/maro")
    async def handle_maro_command(ack, body: dict, respond, logger) -> None:
        """Handle /maro slash commands.

        CRITICAL: ack() MUST be called first, within 3 seconds.
        """
        # Acknowledge immediately (required by Slack)
        await ack()

        command_text = body.get("text", "").strip()
        user_id = body.get("user_id")
        channel_id = body.get("channel_id")

        # Parse subcommand
        parts = command_text.split()
        subcommand = parts[0].lower() if parts else "help"
        args = parts[1:] if len(parts) > 1 else []

        logger.info(f"/maro {subcommand} by {user_id} in {channel_id}")

        # Route to appropriate handler
        match subcommand:
            case "help":
                await _handle_help(respond)
            case "status" | "sync" | "decisions" | "entities" | "config":
                # Deferred per CONTEXT.md - return coming soon message
                await respond(
                    text=f"The `/maro {subcommand}` command is coming soon. "
                         f"This feature requires Phase 4+ functionality.",
                    response_type="ephemeral",
                )
            case _:
                await respond(
                    text=f"Unknown command: `{subcommand}`. Use `/maro help` for available commands.",
                    response_type="ephemeral",
                )


async def _handle_help(respond) -> None:
    """Show help message with available commands."""
    help_text = "*Available MARO commands:*\n\n"
    for cmd, desc in AVAILABLE_COMMANDS.items():
        help_text += f"* `/maro {cmd}` - {desc}\n"

    help_text += "\n_MARO 2.0 - Threads propose. Channels decide. Jira executes._"

    await respond(
        text=help_text,
        response_type="ephemeral",
    )
