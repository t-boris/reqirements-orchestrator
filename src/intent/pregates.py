"""PreGates - Deterministic routing before LLM.

Catches commands, button clicks, explicit approvals to save latency
and ensure predictability.

Ref: RESEARCH.md - Pattern 1: PreGates (Deterministic Pre-Routing)
Ref: BOT_DESIGN.md - Stage 1: PreGates (Deterministic)
"""

import logging
import re

from src.intent.schemas import PreGateResult, PreGateOutput

logger = logging.getLogger(__name__)

# Approval patterns - explicit keywords that trigger APPROVAL gate
APPROVAL_PATTERNS = [
    "approved",
    "lgtm",
    "ship it",
    "+1",
    "looks good",
    "approve",
]

# Objection patterns - explicit keywords that trigger APPROVAL gate (negative)
OBJECTION_PATTERNS = [
    "object",
    "objection",
    "-1",
    "blocked",
    "needs changes",
    "reject",
]


def check_pregates(
    message: str,
    event_type: str,
    *,
    bot_id: str | None = None,
    message_bot_id: str | None = None,
    thread_ts: str | None = None,
    active_workspace_threads: set[str] | None = None,
    active_process_threads: set[str] | None = None,
) -> PreGateOutput:
    """Check PreGates for deterministic routing before LLM.

    Args:
        message: Message text
        event_type: Slack event type (message, app_mention, block_actions, etc.)
        bot_id: Our bot's ID
        message_bot_id: Bot ID from the message (if it's from a bot)
        thread_ts: Thread timestamp (if in a thread)
        active_workspace_threads: Set of thread_ts values with active workspaces (new model)
        active_process_threads: Set of thread_ts values with active processes (legacy)

    Returns:
        PreGateOutput with result and optional data

    Ref: RESEARCH.md - Pattern 1: PreGates
    """
    active_workspace_threads = active_workspace_threads or set()
    active_process_threads = active_process_threads or set()

    # Gate 1: Bot message - ignore
    if message_bot_id:
        logger.debug(f"PreGate: BOT_MESSAGE (bot_id={message_bot_id})")
        return PreGateOutput(result=PreGateResult.BOT_MESSAGE)

    # Gate 2: Button actions - handle directly
    if event_type == "block_actions":
        logger.debug("PreGate: ACTION (block_actions event)")
        return PreGateOutput(result=PreGateResult.ACTION)

    # Gate 3: Slash commands - handle directly
    if message.startswith("/maro"):
        command_parts = message.split(maxsplit=1)
        command = command_parts[0]
        args = command_parts[1] if len(command_parts) > 1 else ""
        logger.debug(f"PreGate: COMMAND (command={command}, args={args})")
        return PreGateOutput(
            result=PreGateResult.COMMAND,
            data={"command": command, "args": args}
        )

    # Gate 4: Known workspace thread - route to Orchestrator
    if thread_ts and thread_ts in active_workspace_threads:
        logger.debug(f"PreGate: WORKSPACE (thread_ts={thread_ts})")
        return PreGateOutput(
            result=PreGateResult.WORKSPACE,
            data={"thread_ts": thread_ts}
        )

    # Gate 4b: Legacy - Known process thread (for backwards compatibility)
    if thread_ts and thread_ts in active_process_threads:
        logger.debug(f"PreGate: PROCESS (thread_ts={thread_ts})")
        return PreGateOutput(
            result=PreGateResult.PROCESS,
            data={"thread_ts": thread_ts}
        )

    # Gate 5: Explicit approval keywords
    message_lower = message.lower().strip()

    # Check approval patterns
    for pattern in APPROVAL_PATTERNS:
        if _matches_pattern(message_lower, pattern):
            logger.debug(f"PreGate: APPROVAL (approve, pattern={pattern})")
            return PreGateOutput(
                result=PreGateResult.APPROVAL,
                data={"action": "approve", "pattern": pattern}
            )

    # Check objection patterns
    for pattern in OBJECTION_PATTERNS:
        if _matches_pattern(message_lower, pattern):
            logger.debug(f"PreGate: APPROVAL (object, pattern={pattern})")
            return PreGateOutput(
                result=PreGateResult.APPROVAL,
                data={"action": "object", "pattern": pattern}
            )

    # No gate matched - pass to LLM
    logger.debug("PreGate: PASS_THROUGH")
    return PreGateOutput(result=PreGateResult.PASS_THROUGH)


def _matches_pattern(message: str, pattern: str) -> bool:
    """Check if message matches a pattern.

    Matches if:
    - Message equals pattern exactly
    - Message starts with pattern followed by punctuation or space
    - Pattern is a word boundary match in the message
    """
    if message == pattern:
        return True

    # Pattern at start followed by punctuation/space
    if message.startswith(pattern) and (
        len(message) == len(pattern) or
        message[len(pattern)] in " !.,;:?"
    ):
        return True

    # Word boundary match (e.g., "lgtm!" matches "lgtm")
    pattern_regex = rf"\b{re.escape(pattern)}\b"
    if re.search(pattern_regex, message):
        return True

    return False
