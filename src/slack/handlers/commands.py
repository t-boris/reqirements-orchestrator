"""Slash command handlers.

Ref: RESEARCH.md - Pattern 4: Slash Command Handler
"""
import logging
from slack_bolt.async_app import AsyncApp

from src.domain.entities import (
    CommittedEntity,
    DraftEntity,
    ProposedEntity,
    ApprovedEntity,
    DeprecatedEntity,
    get_lifecycle,
)
from src.domain.types import EntityType
from src.infrastructure.aggregate_loader import load_aggregate

logger = logging.getLogger(__name__)

# Version from pyproject.toml
__version__ = "2.1.0"

AVAILABLE_COMMANDS = {
    "help": "Show available commands",
    "version": "Show MARO version",
    "status": "Show channel status",
    "sync": "Check Jira sync status (`sync fix` to recreate missing)",
    "decisions": "List active decisions",
    "entities": "List all entities",
    "config": "Show/set channel configuration",
    "inspect": "Debug intent classifications",
}


def register_command_handlers(app: AsyncApp) -> None:
    """Register slash command handlers on the Bolt app."""

    @app.command("/maro")
    async def handle_maro_command(ack, body: dict, respond, client, logger) -> None:
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
            case "version":
                await _handle_version(respond)
            case "status":
                await _handle_status(respond, channel_id)
            case "sync":
                await _handle_sync(respond, client, channel_id, user_id, args)
            case "decisions":
                await _handle_decisions(respond, channel_id)
            case "entities":
                await _handle_entities(respond, channel_id)
            case "config":
                await _handle_config(respond, channel_id, args)
            case "inspect":
                await _handle_inspect(respond, channel_id, args)
            case _:
                await respond(
                    text=f"Unknown command: `{subcommand}`. Use `/maro help` for available commands.",
                    response_type="ephemeral",
                )


async def _handle_help(respond) -> None:
    """Show help message with available commands and interactive buttons."""
    help_text = "*Available MARO commands:*\n\n"
    for cmd, desc in AVAILABLE_COMMANDS.items():
        help_text += f"• `/maro {cmd}` - {desc}\n"

    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": help_text},
        },
        {
            "type": "divider",
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Learn more:*"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📋 My Rules"},
                    "action_id": "help_my_rules",
                    "value": "rules",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❓ How to..."},
                    "action_id": "help_how_to",
                    "value": "howto",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "🎯 Modes"},
                    "action_id": "help_modes",
                    "value": "modes",
                },
            ],
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_MARO v{__version__} - Threads propose. Channels decide. Jira executes._"}],
        },
    ]

    await respond(
        text="MARO Help",
        blocks=blocks,
        response_type="in_channel",
    )


async def _handle_version(respond) -> None:
    """Show MARO version."""
    await respond(
        text=f"*MARO v{__version__}*\n_Threads propose. Channels decide. Jira executes._",
        response_type="ephemeral",
    )


async def _handle_status(respond, channel_id: str) -> None:
    """Show channel status with entity summary."""
    try:
        aggregate = await load_aggregate(channel_id)
        entities = aggregate.entities

        if not entities:
            await respond(
                text=":information_source: No entities in this channel yet.",
                response_type="ephemeral",
            )
            return

        # Count by state
        drafts = sum(1 for e in entities.values() if isinstance(e, DraftEntity))
        proposed = sum(1 for e in entities.values() if isinstance(e, ProposedEntity))
        approved = sum(1 for e in entities.values() if isinstance(e, ApprovedEntity))
        committed = sum(1 for e in entities.values() if isinstance(e, CommittedEntity))

        # Count by type
        work_items = sum(1 for e in entities.values() if e.entity_type == EntityType.WORK_ITEM)
        decisions = sum(1 for e in entities.values() if e.entity_type == EntityType.DECISION)

        status_text = (
            f"*Channel Status*\n\n"
            f"*Total entities:* {len(entities)}\n"
            f"- Work items: {work_items}\n"
            f"- Decisions: {decisions}\n\n"
            f"*By state:*\n"
            f"- Draft: {drafts}\n"
            f"- Proposed (awaiting approval): {proposed}\n"
            f"- Approved (ready for Jira): {approved}\n"
            f"- Committed (in Jira): {committed}\n"
        )

        # List pending approvals
        pending = [e for e in entities.values() if isinstance(e, ProposedEntity)]
        if pending:
            status_text += "\n*Pending approvals:*\n"
            for e in pending[:5]:
                title = getattr(e.content, "title", str(e.id)[:8])
                status_text += f"- {title} ({len(e.approvals)} approvals)\n"

        await respond(
            text=status_text,
            response_type="ephemeral",
        )

    except Exception as e:
        logger.error(f"Status command failed: {e}", exc_info=True)
        await respond(
            text=f":x: Failed to load channel status: {e}",
            response_type="ephemeral",
        )


async def _handle_sync(respond, client, channel_id: str, user_id: str, args: list[str]) -> None:
    """Handle sync command with subcommands.

    Subcommands:
    - /maro sync: Check Jira sync status
    - /maro sync fix: Recreate missing Jira issues
    """
    from src.slack.commands.sync import handle_sync_command

    if args and args[0].lower() == "fix":
        await _handle_sync_fix(respond, client, channel_id, user_id)
        return

    # Default: check sync status
    await handle_sync_command(
        ack=_noop_ack,
        body={"channel_id": channel_id, "user_id": user_id},
        client=client,
    )
    await respond(
        text=":hourglass: Sync check initiated. Results will appear shortly.",
        response_type="ephemeral",
    )


async def _handle_sync_fix(respond, client, channel_id: str, user_id: str) -> None:
    """Recreate missing Jira issues for committed entities.

    Finds committed entities where Jira access fails (issue deleted/missing)
    and creates new Jira issues for them.
    """
    from src.config import get_settings
    from src.domain.entities import CommittedEntity
    from src.domain.types import EntityId, UserId, JiraKey
    from src.infrastructure.aggregate_loader import load_aggregate, save_events
    from src.infrastructure.channel_config import get_jira_project
    from src.jira.factory import get_sync_service, get_reconciliation_service

    await respond(
        text=":hourglass: Checking for missing Jira issues...",
        response_type="ephemeral",
    )

    try:
        settings = get_settings()
        aggregate = await load_aggregate(channel_id)

        # Get channel-specific Jira project
        channel_project = await get_jira_project(channel_id)
        project_key = channel_project or settings.jira_default_project

        committed_entities = [
            e for e in aggregate.entities.values()
            if isinstance(e, CommittedEntity) and e.jira_link
        ]

        if not committed_entities:
            await respond(
                text=":information_source: No committed entities found in this channel.",
                response_type="ephemeral",
            )
            return

        # Check which Jira issues are missing
        recon_service = get_reconciliation_service()
        sync_service = get_sync_service()
        missing_entities = []

        for entity in committed_entities:
            try:
                # Try to access the Jira issue
                await sync_service.jira.get_issue(entity.jira_link.jira_key)
            except Exception as e:
                if "does not exist" in str(e).lower() or "permission" in str(e).lower():
                    missing_entities.append(entity)
                    logger.info(f"Entity {entity.id} has missing Jira issue: {entity.jira_link.jira_key}")

        if not missing_entities:
            await respond(
                text=":white_check_mark: All Jira issues are accessible. Nothing to fix.",
                response_type="ephemeral",
            )
            return

        # Recreate missing issues
        recreated = []
        failed = []

        for entity in missing_entities:
            try:
                old_key = entity.jira_link.jira_key
                title = getattr(entity.content, "title", str(entity.id)[:8])
                description = getattr(entity.content, "description", "")
                issue_type = getattr(entity.content, "issue_type", "Task")
                issue_type_str = issue_type.value if hasattr(issue_type, "value") else str(issue_type)

                # Create new Jira issue
                new_key = await sync_service.jira.create_issue(
                    project_key=project_key,
                    summary=title,
                    issue_type=sync_service._map_issue_type(issue_type_str),
                    description=description,
                )

                # Update entity with new Jira key (need to emit event)
                # For now, just report - updating committed entities requires new event type
                recreated.append(f"• *{title}*: {old_key} → <{settings.jira_url}/browse/{new_key}|{new_key}>")
                logger.info(f"Recreated Jira issue for {entity.id}: {old_key} -> {new_key}")

            except Exception as e:
                title = getattr(entity.content, "title", str(entity.id)[:8])
                failed.append(f"• {title}: {e}")
                logger.error(f"Failed to recreate Jira issue for {entity.id}: {e}")

        # Build response
        response_parts = []
        if recreated:
            response_parts.append(f"*Recreated {len(recreated)} Jira issue(s):*\n" + "\n".join(recreated))
        if failed:
            response_parts.append(f"*Failed to recreate {len(failed)} issue(s):*\n" + "\n".join(failed))

        if recreated:
            response_parts.append("\n:warning: _Note: Internal entity records still reference old Jira keys. Dashboard will show new issues on next refresh._")

        await respond(
            text="\n\n".join(response_parts) if response_parts else "No changes made.",
            response_type="ephemeral",
        )

    except Exception as e:
        logger.error(f"Sync fix failed: {e}", exc_info=True)
        await respond(
            text=f":x: Failed to fix sync issues: {e}",
            response_type="ephemeral",
        )


async def _noop_ack():
    """No-op ack for delegated commands (already acked)."""
    pass


async def _handle_decisions(respond, channel_id: str) -> None:
    """List all decisions in the channel."""
    try:
        aggregate = await load_aggregate(channel_id)
        decisions = [
            e for e in aggregate.entities.values()
            if e.entity_type == EntityType.DECISION
        ]

        if not decisions:
            await respond(
                text=":information_source: No decisions recorded in this channel.",
                response_type="ephemeral",
            )
            return

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"Decisions ({len(decisions)})"},
            },
        ]

        for d in decisions[:10]:
            title = getattr(d.content, "title", str(d.id)[:8])
            state = get_lifecycle(d).value.title()
            dtype = getattr(d.content, "decision_type", "")
            dtype_str = dtype.value if hasattr(dtype, "value") else str(dtype)

            jira_info = ""
            if isinstance(d, CommittedEntity) and d.jira_link:
                jira_info = f" | Jira: {d.jira_link.jira_key}"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{title}*\n_{dtype_str.title()} | {state}{jira_info}_",
                },
            })

        if len(decisions) > 10:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_...and {len(decisions) - 10} more_"}],
            })

        await respond(
            text=f"{len(decisions)} decisions found",
            blocks=blocks,
            response_type="ephemeral",
        )

    except Exception as e:
        logger.error(f"Decisions command failed: {e}", exc_info=True)
        await respond(
            text=f":x: Failed to load decisions: {e}",
            response_type="ephemeral",
        )


async def _handle_entities(respond, channel_id: str) -> None:
    """List all entities in the channel."""
    try:
        aggregate = await load_aggregate(channel_id)
        entities = list(aggregate.entities.values())

        if not entities:
            await respond(
                text=":information_source: No entities in this channel.",
                response_type="ephemeral",
            )
            return

        blocks = [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"All Entities ({len(entities)})"},
            },
        ]

        for e in entities[:15]:
            title = getattr(e.content, "title", str(e.id)[:8])
            state = get_lifecycle(e).value.title()
            etype = e.entity_type.value.replace("_", " ").title()

            jira_info = ""
            if isinstance(e, CommittedEntity) and e.jira_link:
                jira_info = f" | {e.jira_link.jira_key}"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{title}*\n_{etype} | {state}{jira_info}_",
                },
            })

        if len(entities) > 15:
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_...and {len(entities) - 15} more_"}],
            })

        await respond(
            text=f"{len(entities)} entities found",
            blocks=blocks,
            response_type="ephemeral",
        )

    except Exception as e:
        logger.error(f"Entities command failed: {e}", exc_info=True)
        await respond(
            text=f":x: Failed to load entities: {e}",
            response_type="ephemeral",
        )


async def _handle_config(respond, channel_id: str, args: list[str]) -> None:
    """Show or update channel configuration.

    Subcommands:
    - /maro config: Show current configuration
    - /maro config jira-project <KEY>: Set Jira project for this channel
    """
    from src.config import get_settings
    from src.infrastructure.channel_config import get_channel_config, set_jira_project

    settings = get_settings()

    # Handle subcommands
    if args:
        subcommand = args[0].lower()

        if subcommand == "jira-project" and len(args) > 1:
            project_key = args[1].upper()
            try:
                await set_jira_project(channel_id, project_key)
                await respond(
                    text=f":white_check_mark: Jira project set to *{project_key}* for this channel.",
                    response_type="ephemeral",
                )
            except Exception as e:
                logger.error(f"Failed to set Jira project: {e}", exc_info=True)
                await respond(
                    text=f":x: Failed to set Jira project: {e}",
                    response_type="ephemeral",
                )
            return

        elif subcommand == "jira-project":
            await respond(
                text="Usage: `/maro config jira-project <PROJECT_KEY>`\nExample: `/maro config jira-project SCRUM`",
                response_type="ephemeral",
            )
            return

        else:
            await respond(
                text=f"Unknown config option: `{subcommand}`\n\nAvailable options:\n• `jira-project <KEY>` - Set Jira project for this channel",
                response_type="ephemeral",
            )
            return

    # Show current configuration
    try:
        channel_config = await get_channel_config(channel_id)
        jira_project = channel_config.jira_project or settings.jira_default_project
        is_custom = channel_config.jira_project is not None
    except Exception:
        jira_project = settings.jira_default_project
        is_custom = False

    project_display = f"{jira_project}" + (" _(channel override)_" if is_custom else " _(default)_")

    config_text = (
        f"*Channel Configuration*\n\n"
        f"*Channel:* {channel_id}\n"
        f"*Jira Project:* {project_display}\n"
        f"*Jira URL:* {settings.jira_url or 'Not configured'}\n"
        f"*Jira Dry Run:* {settings.jira_dry_run}\n"
        f"*LLM Model:* {settings.llm_model_full}\n"
        f"*Environment:* {settings.environment}\n\n"
        f"_To change Jira project: `/maro config jira-project <KEY>`_"
    )

    await respond(
        text=config_text,
        response_type="ephemeral",
    )


async def _handle_inspect(respond, channel_id: str, args: list[str]) -> None:
    """Show intent classification debug info.

    Subcommands:
    - /maro inspect (no args): Show recent classifications for this channel
    - /maro inspect thread <thread_ts>: Show classifications for a specific thread
    - /maro inspect stats: Show classification distribution stats
    - /maro inspect downgrades: Show threshold downgrade history
    """
    from src.infrastructure.audit_log import query_audit_log
    from src.slack.blocks.inspect import (
        build_thread_inspect_blocks,
        build_stats_inspect_blocks,
        build_downgrades_inspect_blocks,
    )

    subcommand = args[0] if args else "recent"

    try:
        if subcommand == "thread" and len(args) > 1:
            thread_ts = args[1]
            entries = await query_audit_log(channel_id, thread_ts=thread_ts)
            if not entries:
                await respond(
                    text=":information_source: No audit entries for this thread.",
                    response_type="ephemeral",
                )
                return
            blocks = build_thread_inspect_blocks(entries)

        elif subcommand == "stats":
            entries = await query_audit_log(channel_id, limit=200)
            if not entries:
                await respond(
                    text=":information_source: No audit entries yet.",
                    response_type="ephemeral",
                )
                return
            blocks = build_stats_inspect_blocks(entries)

        elif subcommand == "downgrades":
            entries = await query_audit_log(channel_id, limit=200)
            downgrades = [e for e in entries if e.raw_mode != e.classified_mode]
            if not downgrades:
                await respond(
                    text=":white_check_mark: No threshold downgrades found.",
                    response_type="ephemeral",
                )
                return
            blocks = build_downgrades_inspect_blocks(downgrades)

        else:
            # Default: recent classifications
            entries = await query_audit_log(channel_id, limit=15)
            if not entries:
                await respond(
                    text=":information_source: No audit entries yet.",
                    response_type="ephemeral",
                )
                return
            blocks = build_thread_inspect_blocks(entries)

        await respond(
            text=f"Inspect results ({len(entries)} entries)",
            blocks=blocks,
            response_type="ephemeral",
        )

    except Exception as e:
        logger.error(f"Inspect command failed: {e}", exc_info=True)
        await respond(
            text=f":x: Inspect failed: {e}",
            response_type="ephemeral",
        )
