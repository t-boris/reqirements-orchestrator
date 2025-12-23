"""
Slack Handlers - Message and slash command handlers.

Processes incoming messages and routes them to the LangGraph workflow.
"""

import re
from typing import Any

import structlog
from slack_bolt.async_app import AsyncApp

from src.config.settings import get_settings
# Note: graph imports are done lazily inside functions to avoid circular imports
# The import chain graph→nodes→slack→bot→handlers→graph creates a cycle
from src.slack.approval import send_approval_request
from src.slack.channel_config_store import (
    ChannelConfig,
    PersonalityConfig,
    get_channel_config,
    save_channel_config,
    delete_channel_config,
    get_available_models,
)
from src.slack.knowledge_store import (
    get_knowledge_files,
    save_knowledge_file,
    delete_knowledge_file,
    clear_channel_knowledge,
)
from src.slack.formatter import format_response, format_error
from src.slack.handlers.helpers import (
    _get_bot_user_id,
    _process_attachments,
    _format_status,
    _build_config_modal,
    _handle_approval_list,
    _handle_approval_delete,
)
from src.slack.progress import ProgressReporter

logger = structlog.get_logger()
settings = get_settings()


def register_handlers(app: AsyncApp) -> None:
    """
    Register all message and command handlers with the Slack app.

    Args:
        app: Slack Bolt async app instance.
    """
    # =========================================================================
    # Message Handler
    # =========================================================================

    @app.event("message")
    async def handle_message(event: dict, say, client) -> None:
        """
        Handle all incoming messages.

        Processes messages through the LangGraph workflow and responds
        based on confidence thresholds.
        """
        # Lazy imports to avoid circular dependency
        from src.graph.state import create_initial_state
        from src.graph.checkpointer import create_thread_id
        from src.graph.graph import invoke_graph

        # Debug: Log that we received any event
        print(f"[DEBUG] Message event received: subtype={event.get('subtype')}, bot_id={event.get('bot_id')}, text={event.get('text', '')[:50]}")

        # Skip bot messages and message changes
        if event.get("subtype") in ("bot_message", "message_changed", "message_deleted"):
            print(f"[DEBUG] Skipping due to subtype: {event.get('subtype')}")
            return

        # Skip messages from this bot
        if event.get("bot_id"):
            print(f"[DEBUG] Skipping due to bot_id: {event.get('bot_id')}")
            return

        channel_id = event.get("channel", "")
        user_id = event.get("user", "")
        message_text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event.get("ts")
        message_ts = event.get("ts", "")

        # Check if bot was @mentioned
        bot_user_id = await _get_bot_user_id(client)
        is_mention = f"<@{bot_user_id}>" in message_text

        # Remove bot mention from message text
        if is_mention:
            message_text = re.sub(rf"<@{bot_user_id}>", "", message_text).strip()

        # Extract attachments
        attachments = await _process_attachments(event, client)

        logger.info(
            "message_received",
            channel_id=channel_id,
            user_id=user_id,
            is_mention=is_mention,
            has_attachments=len(attachments) > 0,
        )
        print(f"[DEBUG] Processing message from {user_id} in {channel_id}")

        # Initialize progress reporter (will be used for complex operations)
        progress_reporter: ProgressReporter | None = None

        try:
            # Load channel configuration
            print("[DEBUG] Loading channel config...")
            config = await get_channel_config(channel_id)
            print(f"[DEBUG] Config loaded: model={config.default_model}")

            # Always show progress feedback when processing
            progress_reporter = ProgressReporter(client, channel_id, thread_ts)
            await progress_reporter.start("Processing your request...")

            # Create initial state for the graph
            # Create thread ID for checkpointing
            thread_id = create_thread_id(channel_id, thread_ts)
            print(f"[DEBUG] Thread ID: {thread_id}")

            # Load existing state from checkpointer (if any)
            from src.graph.checkpointer import get_thread_state
            existing_state = await get_thread_state(thread_id)
            print(f"[DEBUG] Existing state loaded: phase={existing_state.get('current_phase') if existing_state else None}, has_arch_options={bool(existing_state.get('architecture_options')) if existing_state else False}")

            # Create initial state with new message data
            print("[DEBUG] Creating initial state...")
            state = create_initial_state(
                channel_id=channel_id,
                user_id=user_id,
                message=message_text,
                thread_ts=thread_ts,
                attachments=attachments,
                is_mention=is_mention,
                channel_config=config.to_dict(),
            )

            # Merge existing state (preserve workflow context)
            if existing_state:
                # Preserve important workflow state fields
                preserve_fields = [
                    "current_phase", "phase_history", "architecture_options",
                    "selected_architecture", "chosen_architecture", "current_goal",
                    "discovered_requirements", "clarifying_questions", "user_answers",
                    "epics", "stories", "tasks", "validation_report",
                    "zep_facts", "zep_session_id", "related_jira_issues",
                ]
                for field in preserve_fields:
                    if field in existing_state and existing_state[field] is not None:
                        state[field] = existing_state[field]
                print(f"[DEBUG] Merged existing state: phase={state.get('current_phase')}, arch_options={len(state.get('architecture_options', []))}")

            # Add progress message info to state if we started progress tracking
            if progress_reporter and progress_reporter.message_ts:
                state["progress_message_ts"] = progress_reporter.message_ts
                state["progress_steps"] = progress_reporter.steps

            print(f"[DEBUG] State created, message length={len(message_text)}")

            # Node name to display name mapping for progress updates
            node_display_names = {
                "memory": "Loading memory...",
                "intake": "Analyzing request...",
                "discovery": "Gathering requirements...",
                "architecture": "Exploring architecture options...",
                "scope": "Defining scope...",
                "stories": "Breaking down stories...",
                "tasks": "Detailing tasks...",
                "estimation": "Estimating effort...",
                "security": "Security review...",
                "validation": "Validating requirements...",
                "final_review": "Final review...",
                "human_approval": "Awaiting approval...",
                "jira_write": "Writing to Jira...",
                "jira_read": "Reading from Jira...",
                "jira_status": "Checking status...",
                "jira_add": "Adding to Jira...",
                "jira_update": "Updating Jira...",
                "jira_delete": "Deleting from Jira...",
                "impact_analysis": "Analyzing impact...",
                "memory_update": "Saving to memory...",
                "response": "Preparing response...",
            }

            # Progress callback to update Slack message
            async def on_node_start(node_name: str):
                if progress_reporter and node_name in node_display_names:
                    display_name = node_display_names[node_name]
                    print(f"[DEBUG] Node started: {node_name} -> {display_name}")

                    # Map node to phase for progress update
                    from src.graph.state import WorkflowPhase, ProgressStepStatus
                    node_to_phase = {
                        "intake": WorkflowPhase.INTAKE.value,
                        "discovery": WorkflowPhase.DISCOVERY.value,
                        "architecture": WorkflowPhase.ARCHITECTURE.value,
                        "scope": WorkflowPhase.SCOPE.value,
                        "stories": WorkflowPhase.STORIES.value,
                        "tasks": WorkflowPhase.TASKS.value,
                        "estimation": WorkflowPhase.ESTIMATION.value,
                        "security": WorkflowPhase.SECURITY.value,
                        "validation": WorkflowPhase.VALIDATION.value,
                        "final_review": WorkflowPhase.REVIEW.value,
                    }

                    phase = node_to_phase.get(node_name)
                    if phase:
                        await progress_reporter.start_phase(phase, display_name)

            async def on_node_end(node_name: str, state: dict):
                if progress_reporter:
                    from src.graph.state import WorkflowPhase
                    node_to_phase = {
                        "intake": WorkflowPhase.INTAKE.value,
                        "discovery": WorkflowPhase.DISCOVERY.value,
                        "architecture": WorkflowPhase.ARCHITECTURE.value,
                        "scope": WorkflowPhase.SCOPE.value,
                        "stories": WorkflowPhase.STORIES.value,
                        "tasks": WorkflowPhase.TASKS.value,
                        "estimation": WorkflowPhase.ESTIMATION.value,
                        "security": WorkflowPhase.SECURITY.value,
                        "validation": WorkflowPhase.VALIDATION.value,
                        "final_review": WorkflowPhase.REVIEW.value,
                    }

                    phase = node_to_phase.get(node_name)
                    if phase:
                        await progress_reporter.complete_phase(phase)

            # Invoke the graph with progress callbacks
            print("[DEBUG] Invoking graph...")
            result = await invoke_graph(
                state,
                thread_id,
                on_node_start=on_node_start if progress_reporter else None,
                on_node_end=on_node_end if progress_reporter else None,
            )
            print(f"[DEBUG] Graph result: should_respond={result.get('should_respond')}, error={result.get('error')}, response={result.get('response', '')[:100] if result.get('response') else 'None'}, awaiting_human={result.get('awaiting_human')}")

            # Handle response based on graph output
            if result.get("awaiting_human"):
                # Finish progress before showing approval
                if progress_reporter:
                    await progress_reporter.finish(
                        success=True,
                        message="Ready for review"
                    )

                # Send approval request
                print(f"[DEBUG] Sending approval request, draft={result.get('draft')}")
                try:
                    await send_approval_request(
                        client=client,
                        channel_id=channel_id,
                        thread_ts=thread_ts,
                        draft=result.get("draft", {}),
                        conflicts=result.get("conflicts", []),
                        thread_id=thread_id,
                    )
                    print("[DEBUG] Approval request sent successfully")
                except Exception as e:
                    print(f"[DEBUG] Error sending approval request: {type(e).__name__}: {e}")
                    import traceback
                    traceback.print_exc()

            elif result.get("should_respond") and result.get("response"):
                # For simple responses, remove progress message and just respond
                if progress_reporter:
                    # Check if this was a simple question (not a requirement flow)
                    intent = result.get("intent")
                    if intent in ("question", "general", "off_topic"):
                        # Delete progress message for simple responses
                        try:
                            await client.chat_delete(
                                channel=channel_id,
                                ts=progress_reporter.message_ts,
                            )
                        except Exception:
                            pass  # May not have permission, that's ok
                    else:
                        # Finish progress normally
                        await progress_reporter.finish(success=True)

                # Format and send response
                blocks = format_response(
                    response=result["response"],
                    draft=result.get("draft"),
                    jira_key=result.get("jira_issue_key"),
                )

                # Determine where to send response based on response_target
                response_target = result.get("response_target", "thread")

                if response_target == "channel":
                    # New message in channel (starts new thread)
                    await say(
                        text=result["response"],
                        blocks=blocks,
                        # No thread_ts = new message in channel
                    )
                elif response_target == "broadcast":
                    # Reply in thread but also show in channel
                    await say(
                        text=result["response"],
                        blocks=blocks,
                        thread_ts=thread_ts,
                        reply_broadcast=True,
                    )
                else:
                    # Default: reply in thread
                    await say(
                        text=result["response"],
                        blocks=blocks,
                        thread_ts=thread_ts,
                    )

            elif result.get("error"):
                # Finish progress with error
                if progress_reporter:
                    await progress_reporter.finish(
                        success=False,
                        message=f"Error: {result['error']}"
                    )

                # Send error message
                blocks = format_error(result["error"])
                await say(
                    text=f"Error: {result['error']}",
                    blocks=blocks,
                    thread_ts=thread_ts,
                )
            else:
                # If should_respond is False, clean up progress if shown
                if progress_reporter:
                    try:
                        await client.chat_delete(
                            channel=channel_id,
                            ts=progress_reporter.message_ts,
                        )
                    except Exception:
                        pass

        except Exception as e:
            print(f"[DEBUG] ERROR in message processing: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            logger.exception("message_processing_failed", error=str(e))

            # Clean up progress on error
            if progress_reporter:
                await progress_reporter.finish(
                    success=False,
                    message="An error occurred while processing"
                )

            # Only respond with error if bot was mentioned
            if is_mention:
                await say(
                    text=f"Sorry, I encountered an error processing your message.",
                    thread_ts=thread_ts,
                )

    # =========================================================================
    # App Mention Handler (no-op, handled by message event)
    # =========================================================================

    @app.event("app_mention")
    async def handle_app_mention(event: dict, say, client) -> None:
        """
        Handle @mentions of the bot.

        Note: Mentions are already handled by the message event handler.
        This handler exists to prevent "Unhandled request" warnings in logs.
        """
        # No-op: The message event handler already processes mentions
        pass

    # =========================================================================
    # Slash Commands
    # =========================================================================

    @app.command("/req-status")
    async def handle_status_command(ack, command, client) -> None:
        """
        Show current graph state, metrics, and dashboard links.

        Usage: /req-status
        """
        await ack()

        channel_id = command.get("channel_id", "")
        thread_ts = None  # Commands run in main channel

        try:
            from src.graph.checkpointer import create_thread_id, get_thread_state

            thread_id = create_thread_id(channel_id, thread_ts)
            state = await get_thread_state(thread_id)

            # Build status text
            parts = []

            if state:
                parts.append(_format_status(state))
            else:
                parts.append("No active conversation state in this channel.")

            # Add dashboard links
            parts.append("\n*Dashboards*")
            # LangSmith URL - link to main page, user can find project there
            parts.append(f"• <https://smith.langchain.com/|LangSmith ({settings.langchain_project})> - Tracing & Monitoring")

            # Admin API endpoints
            parts.append(f"• <{settings.external_url}/admin/dashboard|Admin Dashboard> - Zep & LangGraph status")
            parts.append(f"• <{settings.external_url}/admin/zep/sessions|Zep Sessions> - Memory sessions")
            parts.append(f"• <{settings.external_url}/admin/graph/threads|Graph Threads> - Conversation states")

            text = "\n".join(parts)

            await client.chat_postEphemeral(
                channel=channel_id,
                user=command["user_id"],
                text=text,
            )

        except Exception as e:
            logger.error("status_command_failed", error=str(e))
            await client.chat_postEphemeral(
                channel=channel_id,
                user=command["user_id"],
                text=f"Error getting status: {str(e)}",
            )

    @app.command("/req-clean")
    async def handle_clean_command(ack, command, client) -> None:
        """
        Clear memory, state, config, and knowledge for the channel.

        Usage: /req-clean
        """
        await ack()

        channel_id = command.get("channel_id", "")
        user_id = command.get("user_id", "")

        try:
            from src.graph.checkpointer import clear_thread, create_thread_id
            from src.memory import clear_channel_memory

            # Clear graph state
            thread_id = create_thread_id(channel_id, None)
            await clear_thread(thread_id)

            # Clear Zep memory
            await clear_channel_memory(channel_id)

            # Clear channel config
            await delete_channel_config(channel_id)

            # Clear knowledge files
            await clear_channel_knowledge(channel_id)

            await client.chat_postMessage(
                channel=channel_id,
                text=f"<@{user_id}> Channel memory, state, config, and knowledge have been cleared.",
            )

            logger.info("channel_cleaned", channel_id=channel_id, user_id=user_id)

        except Exception as e:
            logger.error("clean_command_failed", error=str(e))
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Error cleaning channel: {str(e)}",
            )

    @app.command("/req-config")
    async def handle_config_command(ack, command, client) -> None:
        """
        Open channel configuration modal.

        Usage: /req-config
        """
        await ack()

        channel_id = command["channel_id"]

        # Load current config
        config = await get_channel_config(channel_id)
        knowledge_files = await get_knowledge_files(channel_id)

        # Open configuration modal
        await client.views_open(
            trigger_id=command["trigger_id"],
            view=_build_config_modal(config, knowledge_files),
        )

    @app.command("/req-approve")
    async def handle_approve_command(ack, command, client) -> None:
        """
        Manage permanent approvals.

        Usage:
            /req-approve list - List all approvals
            /req-approve delete <id> - Delete an approval
        """
        await ack()

        channel_id = command.get("channel_id", "")
        user_id = command.get("user_id", "")
        args = command.get("text", "").strip().split()

        if not args or args[0] == "list":
            await _handle_approval_list(client, channel_id, user_id)
        elif args[0] == "delete" and len(args) > 1:
            await _handle_approval_delete(client, channel_id, user_id, args[1])
        else:
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text="Usage: `/req-approve list` or `/req-approve delete <id>`",
            )

    # =========================================================================
    # Button Actions
    # =========================================================================

    @app.action(re.compile(r"^approve_"))
    async def handle_approve_action(ack, body, client) -> None:
        """Handle approval button clicks."""
        await ack()

        from src.slack.approval import handle_approval_action

        await handle_approval_action(body, client)

    @app.action(re.compile(r"^edit_"))
    async def handle_edit_action(ack, body, client) -> None:
        """Handle edit button clicks - opens modal."""
        await ack()

        from src.slack.approval import handle_edit_action

        await handle_edit_action(body, client)

    @app.action(re.compile(r"^reject_"))
    async def handle_reject_action(ack, body, client) -> None:
        """Handle reject button clicks."""
        await ack()

        from src.slack.approval import handle_reject_action

        await handle_reject_action(body, client)

    # =========================================================================
    # Modal Submissions
    # =========================================================================

    @app.view("config_modal")
    async def handle_config_submit(ack, body, view, client) -> None:
        """Handle configuration modal submission."""
        await ack()

        # Extract values from modal
        values = view.get("state", {}).get("values", {})
        channel_id = view.get("private_metadata", "")
        user_id = body.get("user", {}).get("id", "")

        try:
            # Extract form values
            project_key = values.get("project_key", {}).get("project_key_input", {}).get("value")
            issue_type = values.get("default_issue_type", {}).get("issue_type_select", {}).get("selected_option", {}).get("value", "Story")
            model = values.get("llm_model", {}).get("model_select", {}).get("selected_option", {}).get("value", "gpt-5.2")

            # Personality values (0-10 scale, convert to 0.0-1.0)
            humor = int(values.get("personality_humor", {}).get("humor_input", {}).get("value") or "2") / 10.0
            formality = int(values.get("personality_formality", {}).get("formality_input", {}).get("value") or "6") / 10.0
            emoji = int(values.get("personality_emoji", {}).get("emoji_input", {}).get("value") or "2") / 10.0
            verbosity = int(values.get("personality_verbosity", {}).get("verbosity_input", {}).get("value") or "5") / 10.0

            # Inline knowledge for personas
            architect_knowledge = values.get("architect_knowledge", {}).get("architect_knowledge_input", {}).get("value") or ""
            pm_knowledge = values.get("pm_knowledge", {}).get("pm_knowledge_input", {}).get("value") or ""
            security_knowledge = values.get("security_knowledge", {}).get("security_knowledge_input", {}).get("value") or ""

            # Build config object
            config = ChannelConfig(
                channel_id=channel_id,
                jira_project_key=project_key,
                jira_default_issue_type=issue_type,
                default_model=model,
                personality=PersonalityConfig(
                    humor=max(0.0, min(1.0, humor)),
                    formality=max(0.0, min(1.0, formality)),
                    emoji_usage=max(0.0, min(1.0, emoji)),
                    verbosity=max(0.0, min(1.0, verbosity)),
                ),
                persona_knowledge={
                    "architect": {"inline": architect_knowledge},
                    "product_manager": {"inline": pm_knowledge},
                    "security_analyst": {"inline": security_knowledge},
                },
            )

            # Save to database
            await save_channel_config(config)

            await client.chat_postMessage(
                channel=channel_id,
                text=f"<@{user_id}> Channel configuration saved successfully.\n"
                     f"• Model: `{model}`\n"
                     f"• Jira Project: `{project_key or 'Not set'}`",
            )

        except Exception as e:
            logger.exception("config_save_failed", error=str(e))
            await client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                text=f"Failed to save configuration: {str(e)}",
            )

    @app.view("edit_requirement_modal")
    async def handle_edit_submit(ack, body, view, client) -> None:
        """Handle requirement edit modal submission."""
        await ack()

        from src.slack.approval import process_edit_submission

        await process_edit_submission(body, view, client)

