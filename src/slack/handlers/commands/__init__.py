"""Commands package - /maro, /jira, /help slash command handlers.

This package organizes slash command handlers by domain:
- router: Main command routing and core handlers (enable/disable/status, track/board, mode/project)
- debug: Debug mode control and state inspection
- sync: Jira synchronization commands
- decisions: Decision management commands
- explain: OPS explain functionality
- help: Interactive help

Usage:
    from src.slack.handlers.commands import (
        handle_maro_command,
        handle_jira_command,
        handle_help_command,
    )
"""

# Main entry points from router
from src.slack.handlers.commands.router import (
    handle_maro_command,
    handle_jira_command,
    handle_help_command,
)

# Individual command handlers for direct access
from src.slack.handlers.commands.debug import handle_debug_command
from src.slack.handlers.commands.sync import handle_sync_command
from src.slack.handlers.commands.decisions import (
    handle_decisions_command,
    handle_decision_subcommand,
)
from src.slack.handlers.commands.explain import handle_explain_command
from src.slack.handlers.commands.help import handle_help_command as handle_maro_help

__all__ = [
    # Main entry points (used by handlers/__init__.py)
    "handle_maro_command",
    "handle_jira_command",
    "handle_help_command",
    # Individual handlers for direct access
    "handle_debug_command",
    "handle_sync_command",
    "handle_decisions_command",
    "handle_decision_subcommand",
    "handle_explain_command",
    "handle_maro_help",
]
