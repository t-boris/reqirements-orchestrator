"""Decision command handlers: /maro decisions, /maro decision <subcommand>.

Handles decision listing, viewing, enrichment, and delegation to modals.
"""

import logging

from slack_sdk.web import WebClient

logger = logging.getLogger(__name__)


async def handle_decisions_command(
    command: dict,
    client: WebClient,
):
    """Handle /maro decisions command - list channel decisions.

    Delegates to the decision_commands module for full implementation.
    """
    from src.slack.handlers.decision_commands import _handle_decisions_command_async

    await _handle_decisions_command_async(command, client)


async def handle_decision_subcommand(
    command: dict,
    args: list[str],
    client: WebClient,
    say,
):
    """Handle /maro decision <subcommand> commands.

    Subcommands:
    - show <id> - Show decision details
    - change <id> - Open change modal
    - deprecate <id> - Open deprecation modal
    - enrich <id> - Extract rich context
    - needs-context - List decisions needing enrichment
    """
    from src.slack.handlers.decision_commands import (
        _handle_decision_show_async,
        _handle_decision_change_async,
        _handle_decision_deprecate_async,
    )

    channel_id = command.get("channel_id")

    if not args:
        say(
            text="Usage:\n"
                 "- `/maro decision show <id>` - Show decision details\n"
                 "- `/maro decision change <id>` - Propose a change\n"
                 "- `/maro decision deprecate <id>` - Deprecate decision\n"
                 "- `/maro decision enrich <id>` - Extract rich context\n"
                 "- `/maro decision needs-context` - List decisions needing context",
            channel=channel_id,
        )
        return

    subcommand = args[0].lower()
    # Rebuild text with remaining args for the handlers
    command["text"] = " ".join(args)

    if subcommand == "show":
        await _handle_decision_show_async(command, client)
    elif subcommand == "change":
        await _handle_decision_change_async(command, client)
    elif subcommand == "deprecate":
        await _handle_decision_deprecate_async(command, client)
    elif subcommand == "enrich":
        if len(args) < 2:
            say(
                text="Usage: `/maro decision enrich <id>` - Enrich decision with context",
                channel=channel_id,
            )
            return
        await _handle_decision_enrich(
            channel_id=channel_id,
            user_id=command.get("user_id"),
            decision_id=args[1],
            client=client,
        )
    elif subcommand == "needs-context":
        await _handle_decision_needs_context(
            channel_id=channel_id,
            user_id=command.get("user_id"),
            client=client,
        )
    else:
        say(
            text=f"Unknown decision subcommand: `{subcommand}`\n\n"
                 "Available: show, change, deprecate, enrich, needs-context",
            channel=channel_id,
        )


async def _handle_decision_enrich(
    channel_id: str,
    user_id: str,
    decision_id: str,
    client: WebClient,
) -> None:
    """Handle /maro decision enrich DEC-xxx command.

    Extracts rich context from decision's discussion thread
    and updates the decision.

    Args:
        channel_id: Slack channel ID
        user_id: User who invoked command
        decision_id: Decision ID (short or full UUID)
        client: Slack client
    """
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore
    from src.graph.nodes.decision_extraction import extract_rich_context

    # Normalize decision ID (handle DEC-xxx format)
    if decision_id.upper().startswith("DEC-"):
        decision_id = decision_id[4:]

    async with get_connection() as conn:
        store = DecisionStore(conn)

        # Get decision
        decision = await store.get(decision_id)
        if not decision:
            # Try prefix match
            decisions = await store.list_by_channel(channel_id, limit=100)
            matches = [d for d in decisions if d.id.startswith(decision_id)]
            if len(matches) == 1:
                decision = matches[0]
            elif len(matches) > 1:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=f"Multiple decisions match `{decision_id}`. Please be more specific.",
                )
                return
            else:
                client.chat_postEphemeral(
                    channel=channel_id,
                    user=user_id,
                    text=f"Decision `{decision_id}` not found.",
                )
                return

        # Check if already has rich context
        if decision.has_rich_context():
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Decision DEC-{decision.id[:8]} already has rich context. Use `/maro decision show` to view.",
            )
            return

        # Get conversation from discussion thread
        conversation = ""
        if decision.discussion_thread_ts:
            try:
                result = client.conversations_replies(
                    channel=channel_id,
                    ts=decision.discussion_thread_ts,
                    limit=20,
                )
                messages = result.get("messages", [])
                conversation = "\n\n---\n\n".join(
                    m.get("text", "") for m in messages if m.get("text")
                )
            except Exception as e:
                logger.warning(f"Failed to fetch discussion thread: {e}")

        # If no thread, use description as context
        if not conversation:
            conversation = decision.description

        # Post progress message
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text=f"Extracting rich context for DEC-{decision.id[:8]}...",
        )

        # Extract rich context
        rich_context = await extract_rich_context(
            title=decision.title,
            description=decision.description,
            conversation_context=conversation,
        )

        # Update decision
        if any(rich_context.values()):
            await store.update_rich_context(
                decision_id=decision.id,
                rationale=rich_context.get("rationale"),
                context_before=rich_context.get("context_before"),
                alternatives=rich_context.get("alternatives"),
                consequences=rich_context.get("consequences"),
                updated_by=user_id,
            )

            # Build summary of what was extracted
            extracted = []
            if rich_context.get("rationale"):
                extracted.append(f"{len(rich_context['rationale'])} rationale points")
            if rich_context.get("context_before"):
                extracted.append("context")
            if rich_context.get("alternatives"):
                extracted.append(f"{len(rich_context['alternatives'])} alternatives")
            if rich_context.get("consequences"):
                extracted.append(f"{len(rich_context['consequences'])} consequences")

            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Enriched DEC-{decision.id[:8]} with: {', '.join(extracted)}.\nUse `/maro decision show {decision.id[:8]}` to view.",
            )
        else:
            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Could not extract rich context for DEC-{decision.id[:8]}. Try adding more context to the discussion thread.",
            )


async def _handle_decision_needs_context(
    channel_id: str,
    user_id: str,
    client: WebClient,
) -> None:
    """Handle /maro decision needs-context command.

    Lists decisions in channel that lack rich context.
    """
    from src.db.connection import get_connection
    from src.db.decision_store import DecisionStore

    async with get_connection() as conn:
        store = DecisionStore(conn)
        decisions = await store.list_without_rich_context(channel_id, limit=10)

    if not decisions:
        client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="All decisions in this channel have rich context!",
        )
        return

    # Build list
    lines = ["*Decisions needing rich context:*\n"]
    for d in decisions:
        type_emoji = {
            "arch": "brain",
            "scope": "triangular_ruler",
            "constraint": "lock",
            "priority": "zap",
            "structure": "building_construction",
            "process": "gear",
        }.get(d.decision_type.value, "clipboard")
        lines.append(f":{type_emoji}: `DEC-{d.id[:8]}` {d.title[:50]}")

    lines.append(f"\nUse `/maro decision enrich DEC-xxx` to add context.")

    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text="\n".join(lines),
    )
