"""
Slack Handlers - Business logic for Slack events.

Processes messages and commands, routing them to the agent orchestrator.
"""

import structlog
from typing import Callable, Any

from src.adapters.slack.formatter import SlackFormatter
from src.adapters.slack.config import ChannelConfig, ChannelSettings
from src.core.agents.orchestrator import AgentOrchestrator
from src.core.services.graph_service import GraphService
from src.core.graph.models import NodeType

logger = structlog.get_logger()


class SlackHandlers:
    """
    Handlers for Slack events and commands.

    Routes messages to the agent orchestrator and formats responses.
    """

    def __init__(
        self,
        orchestrator: AgentOrchestrator,
        graph_service: GraphService,
        channel_config: ChannelConfig,
        formatter: SlackFormatter,
    ) -> None:
        """
        Initialize handlers.

        Args:
            orchestrator: Agent orchestrator for processing messages.
            graph_service: Graph service for direct operations.
            channel_config: Channel configuration (Jira mapping).
            formatter: Slack message formatter.
        """
        self._orchestrator = orchestrator
        self._graph_service = graph_service
        self._channel_config = channel_config
        self._formatter = formatter

    async def handle_message(
        self,
        channel_id: str,
        user_id: str,
        text: str,
        thread_ts: str | None,
        say: Callable,
        client: Any,
    ) -> None:
        """
        Handle incoming message.

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user ID.
            text: Message text.
            thread_ts: Thread timestamp (if in thread).
            say: Function to send response.
            client: Slack client.
        """
        if not text or not text.strip():
            return

        logger.info(
            "handling_message",
            channel_id=channel_id,
            user_id=user_id,
            text_length=len(text),
        )

        try:
            # Show typing indicator
            await client.reactions_add(
                channel=channel_id,
                name="thinking_face",
                timestamp=thread_ts or "",
            )
        except Exception:
            pass  # Ignore reaction errors

        try:
            # Process through agent orchestrator
            result = await self._orchestrator.process_message(
                channel_id=channel_id,
                user_id=user_id,
                message=text,
            )

            # Format and send response
            response = self._formatter.format_response(result)

            await say(
                text=response["text"],
                blocks=response.get("blocks"),
                thread_ts=thread_ts,
            )

            # Remove thinking indicator
            try:
                await client.reactions_remove(
                    channel=channel_id,
                    name="thinking_face",
                    timestamp=thread_ts or "",
                )
            except Exception:
                pass

        except Exception as e:
            logger.error("message_handling_error", error=str(e))
            await say(
                text=f"Sorry, I encountered an error: {str(e)}",
                thread_ts=thread_ts,
            )

    async def handle_status_command(
        self,
        channel_id: str,
        user_id: str,
        say: Callable,
    ) -> None:
        """
        Handle /req-status command.

        Shows current graph state and metrics.

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user ID.
            say: Function to send response.
        """
        logger.info("handling_status_command", channel_id=channel_id)

        try:
            state = self._graph_service.get_graph_state(channel_id)
            response = self._formatter.format_status(state)

            await say(
                text=response["text"],
                blocks=response.get("blocks"),
            )

        except Exception as e:
            logger.error("status_command_error", error=str(e))
            await say(text=f"Error getting status: {str(e)}")

    async def handle_nfr_command(
        self,
        channel_id: str,
        user_id: str,
        text: str,
        say: Callable,
    ) -> None:
        """
        Handle /req-nfr command.

        Adds a non-functional requirement (constraint) to the graph.

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user ID.
            text: NFR description (e.g., "GDPR compliance required")
            say: Function to send response.
        """
        logger.info("handling_nfr_command", channel_id=channel_id, text=text)

        if not text.strip():
            await say(
                text="Please provide an NFR description. Example: `/req-nfr GDPR compliance required`"
            )
            return

        try:
            # Parse NFR type if provided
            nfr_types = {
                "gdpr": "compliance",
                "security": "security",
                "performance": "performance",
                "latency": "latency",
                "scalability": "scalability",
                "availability": "availability",
            }

            nfr_type = "general"
            for key, value in nfr_types.items():
                if key in text.lower():
                    nfr_type = value
                    break

            # Create constraint node
            node = self._graph_service.add_node(
                channel_id=channel_id,
                user_id=user_id,
                node_type=NodeType.CONSTRAINT,
                title=text,
                description=f"Non-functional requirement: {text}",
                type=nfr_type,
            )

            await say(
                text=f"Added NFR constraint: *{text}*\nNode ID: `{node.id}`",
            )

        except Exception as e:
            logger.error("nfr_command_error", error=str(e))
            await say(text=f"Error adding NFR: {str(e)}")

    async def handle_clean_command(
        self,
        channel_id: str,
        user_id: str,
        say: Callable,
    ) -> None:
        """
        Handle /req-clean command.

        Clears the entire graph for this channel.

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user ID.
            say: Function to send response.
        """
        logger.info("handling_clean_command", channel_id=channel_id)

        try:
            result = self._graph_service.clear_graph(
                channel_id=channel_id,
                user_id=user_id,
            )

            # Also clear the agent session
            self._orchestrator.clear_session(channel_id)

            await say(
                text=f"Graph cleared. Removed {result['nodes']} nodes and {result['edges']} edges.",
            )

        except Exception as e:
            logger.error("clean_command_error", error=str(e))
            await say(text=f"Error clearing graph: {str(e)}")

    async def handle_reset_command(
        self,
        channel_id: str,
        user_id: str,
        say: Callable,
    ) -> None:
        """
        Handle /req-reset command.

        Clears the knowledge base and recreates it from scratch.
        This performs a full reset including:
        - Clearing the graph
        - Clearing the event store
        - Clearing the agent session
        - Reinitializing the channel

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user ID.
            say: Function to send response.
        """
        logger.info("handling_reset_command", channel_id=channel_id)

        try:
            # Get current state for reporting
            state = self._graph_service.get_graph_state(channel_id)
            old_nodes = state.get("metrics", {}).get("total_nodes", 0)
            old_edges = state.get("metrics", {}).get("total_edges", 0)

            # Clear the graph
            self._graph_service.clear_graph(
                channel_id=channel_id,
                user_id=user_id,
            )

            # Clear agent session
            self._orchestrator.clear_session(channel_id)

            # Clear event store for this channel
            from src.core.events.store import EventStore
            event_store = self._graph_service._event_store
            events_cleared = event_store.clear_channel(channel_id)

            # Reinitialize - create fresh graph
            self._graph_service.get_or_create_graph(channel_id)

            await say(
                text=(
                    f":recycle: *Knowledge base reset complete*\n"
                    f"Cleared: {old_nodes} nodes, {old_edges} edges, {events_cleared} events\n"
                    f"A fresh graph has been initialized for this channel."
                ),
            )

        except Exception as e:
            logger.error("reset_command_error", error=str(e))
            await say(text=f"Error resetting knowledge base: {str(e)}")

    def get_channel_settings(self, channel_id: str) -> ChannelSettings | None:
        """
        Get current settings for a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Channel settings or None if not configured.
        """
        return self._channel_config.get_channel(channel_id)

    def update_channel_settings(self, channel_id: str, **updates: Any) -> ChannelSettings:
        """
        Update channel settings.

        Args:
            channel_id: Slack channel ID.
            **updates: Fields to update.

        Returns:
            Updated channel settings.
        """
        settings = self._channel_config.update_channel(channel_id, **updates)
        logger.info("channel_settings_updated", channel_id=channel_id, updates=list(updates.keys()))

        # Clear agent session so new settings take effect
        self._orchestrator.clear_session(channel_id)

        return settings
