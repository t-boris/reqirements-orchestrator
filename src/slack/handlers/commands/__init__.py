"""Commands package - /maro slash command handlers.

This package organizes slash command handlers by domain:
- debug: Debug mode control and state inspection
- sync: Jira synchronization commands
- decisions: Decision management commands
- explain: OPS explain functionality
- help: Interactive help
- router: Main command routing

Usage:
    from src.slack.handlers.commands import register_commands
    register_commands(app)
"""

from src.slack.handlers.commands.debug import handle_debug_command
from src.slack.handlers.commands.sync import handle_sync_command
from src.slack.handlers.commands.decisions import (
    handle_decisions_command,
    handle_decision_subcommand,
)
from src.slack.handlers.commands.explain import handle_explain_command

__all__ = [
    "handle_debug_command",
    "handle_sync_command",
    "handle_decisions_command",
    "handle_decision_subcommand",
    "handle_explain_command",
]
