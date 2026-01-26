"""Channel configuration command handlers: mode, project.

Handles channel mode and default project configuration commands.
"""

import logging

logger = logging.getLogger(__name__)


async def handle_mode_command(
    channel_id: str,
    user_id: str,
    args: list[str],
    say,
):
    """Handle /maro mode command - view or set channel mode.

    Usage:
    - /maro mode              - Show current mode
    - /maro mode project      - Full work item types
    - /maro mode feature --primary-epic PROJ-50 - Focus on one epic
    - /maro mode bugs         - Bug/task focused
    - /maro mode ops          - Incidents, runbooks
    """
    from src.db import get_connection
    from src.db.channel_mode_store import ChannelModeStore
    from src.db.models import ChannelMode

    # Parse arguments
    mode_arg = args[0].lower() if args else None
    primary_epic = None

    # Check for --primary-epic flag
    if "--primary-epic" in args or "-e" in args:
        try:
            flag_idx = args.index("--primary-epic") if "--primary-epic" in args else args.index("-e")
            if flag_idx + 1 < len(args):
                primary_epic = args[flag_idx + 1].upper()
        except (ValueError, IndexError):
            pass

    try:
        async with get_connection() as conn:
            store = ChannelModeStore(conn)
            await store.create_tables()

            # View current mode
            if not mode_arg:
                config = await store.get(channel_id)
                if not config:
                    say(
                        text="*Channel Mode:* project (default)\n\n"
                             "Use `/maro mode <mode>` to change. Available modes:\n"
                             "- `project` - Full work item types\n"
                             "- `feature --primary-epic PROJ-50` - Focus on one epic\n"
                             "- `bugs` - Bug/task focused\n"
                             "- `ops` - Incidents, runbooks",
                        channel=channel_id,
                    )
                else:
                    mode_desc = _get_mode_description(config.mode)
                    epic_info = f" (primary epic: {config.primary_epic})" if config.primary_epic else ""
                    set_info = f"\nSet by <@{config.set_by}>" if config.set_by else ""
                    say(
                        text=f"*Channel Mode:* {config.mode.value}{epic_info}\n"
                             f"{mode_desc}{set_info}",
                        channel=channel_id,
                    )
                return

            # Set mode
            valid_modes = {m.value: m for m in ChannelMode}
            if mode_arg not in valid_modes:
                say(
                    text=f"Unknown mode: `{mode_arg}`\n\n"
                         f"Available modes: {', '.join(valid_modes.keys())}",
                    channel=channel_id,
                )
                return

            mode = valid_modes[mode_arg]

            # Validate primary_epic for feature mode
            if mode == ChannelMode.FEATURE and not primary_epic:
                say(
                    text="Feature mode requires a primary epic.\n"
                         "Usage: `/maro mode feature --primary-epic PROJ-50`",
                    channel=channel_id,
                )
                return

            # Clear primary_epic if not feature mode
            if mode != ChannelMode.FEATURE:
                primary_epic = None

            # Set the mode
            config = await store.set_mode(channel_id, mode, user_id, primary_epic=primary_epic)

            mode_desc = _get_mode_description(mode)
            epic_info = f" with primary epic {primary_epic}" if primary_epic else ""
            say(
                text=f"Channel mode set to *{mode.value}*{epic_info}\n\n{mode_desc}",
                channel=channel_id,
            )

            logger.info(
                "Channel mode set",
                extra={
                    "channel_id": channel_id,
                    "mode": mode.value,
                    "primary_epic": primary_epic,
                    "set_by": user_id,
                }
            )

    except Exception as e:
        logger.error(f"Failed to handle mode command: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't process the mode command. Please try again.",
            channel=channel_id,
        )


def _get_mode_description(mode: "ChannelMode") -> str:
    """Get human-readable description for a channel mode."""
    from src.db.models import ChannelMode

    descriptions = {
        ChannelMode.PROJECT: "Full work item types enabled. All MARO features available.",
        ChannelMode.FEATURE: "Focused on primary epic. Stories and tasks preferred.",
        ChannelMode.BUGS: "Bug and task focused. Epic creation suppressed.",
        ChannelMode.OPS: "Incidents and runbooks. Stricter Jira writes.",
    }
    return descriptions.get(mode, "")


async def handle_project_command(
    channel_id: str,
    team_id: str,
    user_id: str,
    args: list[str],
    say,
) -> None:
    """Handle /maro project command.

    Usage:
    - /maro project           - Show current default project
    - /maro project SCRUM     - Set default Jira project to SCRUM
    - /maro project --clear   - Clear default project (use global)
    """
    from src.db import get_connection
    from src.db.channel_context_store import ChannelContextStore
    from src.db.models import ChannelConfig

    project_arg = args[0].upper() if args else None

    try:
        async with get_connection() as conn:
            store = ChannelContextStore(conn)
            await store.create_tables()

            ctx = await store.get_or_create(team_id, channel_id)

            # View current project
            if not project_arg:
                current = ctx.config.default_jira_project
                if current:
                    say(
                        text=f"*Default Jira Project:* `{current}`\n\n"
                             f"Tickets created in this channel will use this project.\n"
                             f"Use `/maro project <KEY>` to change.",
                        channel=channel_id,
                    )
                else:
                    from src.config.settings import get_settings
                    settings = get_settings()
                    global_proj = settings.jira_default_project
                    if global_proj:
                        say(
                            text=f"*Default Jira Project:* Not set for this channel\n\n"
                                 f"Using global default: `{global_proj}`\n"
                                 f"Use `/maro project <KEY>` to set a channel-specific project.",
                            channel=channel_id,
                        )
                    else:
                        say(
                            text="*Default Jira Project:* Not set\n\n"
                                 "Use `/maro project <KEY>` to set a default project for this channel.",
                            channel=channel_id,
                        )
                return

            # Clear project
            if project_arg == "--CLEAR":
                new_config = ChannelConfig(
                    default_jira_project=None,
                    secondary_projects=ctx.config.secondary_projects,
                    trigger_rule=ctx.config.trigger_rule,
                    epic_binding_behavior=ctx.config.epic_binding_behavior,
                    config_permissions=ctx.config.config_permissions,
                )
                await store.update_config(team_id, channel_id, new_config)
                say(
                    text="Default Jira project cleared for this channel.",
                    channel=channel_id,
                )
                return

            # Validate project key format
            if not project_arg.isalpha() or len(project_arg) < 2:
                say(
                    text=f"Invalid project key: `{project_arg}`\n\n"
                         f"Project keys should be uppercase letters (e.g., SCRUM, PROJ).",
                    channel=channel_id,
                )
                return

            # Set project
            new_config = ChannelConfig(
                default_jira_project=project_arg,
                secondary_projects=ctx.config.secondary_projects,
                trigger_rule=ctx.config.trigger_rule,
                epic_binding_behavior=ctx.config.epic_binding_behavior,
                config_permissions=ctx.config.config_permissions,
            )
            await store.update_config(team_id, channel_id, new_config)

            say(
                text=f"Default Jira project set to `{project_arg}` for this channel.\n\n"
                     f"All tickets created here will use this project.",
                channel=channel_id,
            )

            logger.info(
                "Channel default project set",
                extra={
                    "channel_id": channel_id,
                    "project": project_arg,
                    "set_by": user_id,
                }
            )

    except Exception as e:
        logger.error(f"Failed to handle project command: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't process the project command. Please try again.",
            channel=channel_id,
        )
