"""
Agent Orchestrator - Manages the AutoGen GroupChat session.

Coordinates the conversation between agents and handles
message routing from Slack.
"""

import structlog
import autogen

from src.adapters.slack.config import ChannelConfig, ChannelSettings
from src.core.agents.graph_admin import GraphAdmin
from src.core.agents.architect import SoftwareArchitect
from src.core.agents.product_manager import ProductManager
from src.core.agents.prompts import (
    CONTEXT_INJECTION_TEMPLATE,
    PRODUCT_MANAGER_PROMPT,
    SOFTWARE_ARCHITECT_PROMPT,
    GRAPH_ADMIN_PROMPT,
)
from src.core.services.graph_service import GraphService
from src.core.services.summarization_service import SummarizationService
from src.config.settings import Settings

logger = structlog.get_logger()


class AgentOrchestrator:
    """
    Orchestrates the multi-agent conversation.

    Manages the AutoGen GroupChat with three agents:
    - GraphAdmin: Executes graph operations
    - SoftwareArchitect: Technical validation
    - ProductManager: Business value validation

    Handles context injection and summarization.
    """

    def __init__(
        self,
        graph_service: GraphService,
        summarization_service: SummarizationService,
        settings: Settings,
        channel_config: ChannelConfig | None = None,
    ) -> None:
        """
        Initialize the orchestrator.

        Args:
            graph_service: Service for graph operations.
            summarization_service: Service for context summarization.
            settings: Application settings.
            channel_config: Channel configuration for per-channel settings.
        """
        self._graph_service = graph_service
        self._summarization_service = summarization_service
        self._settings = settings
        self._channel_config = channel_config or ChannelConfig()

        # Default LLM configuration for AutoGen
        self._default_llm_config = {
            "config_list": [
                {
                    "model": settings.llm_model_main,
                    "api_key": settings.openai_api_key,
                }
            ],
            "temperature": 0.7,
        }

        # Active sessions: channel_id -> session components
        self._sessions: dict[str, dict] = {}

    def _get_llm_config(self, channel_settings: ChannelSettings | None) -> dict:
        """
        Get LLM config for a channel, using channel settings if available.

        Args:
            channel_settings: Channel-specific settings or None.

        Returns:
            LLM configuration dict for AutoGen.
        """
        if not channel_settings or not channel_settings.llm_model:
            return self._default_llm_config

        # Determine API key based on provider
        provider = channel_settings.llm_provider or "openai"
        if provider == "anthropic":
            api_key = self._settings.anthropic_api_key
        elif provider == "google":
            api_key = self._settings.google_api_key
        else:
            api_key = self._settings.openai_api_key

        # Convert temperature from 0-100 to 0.0-1.0
        temperature = channel_settings.temperature / 100.0

        return {
            "config_list": [
                {
                    "model": channel_settings.llm_model,
                    "api_key": api_key,
                }
            ],
            "temperature": temperature,
        }

    def _get_prompts(self, channel_settings: ChannelSettings | None) -> dict[str, str]:
        """
        Get agent prompts for a channel, with personality modifiers.

        Args:
            channel_settings: Channel-specific settings or None.

        Returns:
            Dict with prompt keys: pm, architect, graph_admin.
        """
        base_pm = PRODUCT_MANAGER_PROMPT
        base_arch = SOFTWARE_ARCHITECT_PROMPT
        base_admin = GRAPH_ADMIN_PROMPT

        if channel_settings:
            # Use custom prompts if set
            if channel_settings.prompt_product_manager:
                base_pm = channel_settings.prompt_product_manager
            if channel_settings.prompt_architect:
                base_arch = channel_settings.prompt_architect
            if channel_settings.prompt_graph_admin:
                base_admin = channel_settings.prompt_graph_admin

            # Add personality modifier
            personality = channel_settings.get_personality_modifier()
            base_pm = base_pm + "\n" + personality
            base_arch = base_arch + "\n" + personality

        return {
            "pm": base_pm,
            "architect": base_arch,
            "graph_admin": base_admin,
        }

    def get_or_create_session(
        self,
        channel_id: str,
        user_id: str,
    ) -> dict:
        """
        Get or create a session for a channel.

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user ID.

        Returns:
            Session dictionary with agents and group chat.
        """
        if channel_id not in self._sessions:
            self._sessions[channel_id] = self._create_session(channel_id, user_id)
        return self._sessions[channel_id]

    def _create_session(self, channel_id: str, user_id: str) -> dict:
        """
        Create a new agent session.

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user ID.

        Returns:
            Session dictionary with initialized agents.
        """
        logger.info("creating_agent_session", channel_id=channel_id)

        # Get channel-specific settings
        channel_settings = self._channel_config.get_channel(channel_id)

        # Get LLM config and prompts for this channel
        llm_config = self._get_llm_config(channel_settings)
        prompts = self._get_prompts(channel_settings)

        logger.info(
            "session_config",
            channel_id=channel_id,
            model=llm_config["config_list"][0]["model"],
            has_custom_prompts=bool(
                channel_settings and (
                    channel_settings.prompt_product_manager or
                    channel_settings.prompt_architect or
                    channel_settings.prompt_graph_admin
                )
            ) if channel_settings else False,
        )

        # Create agents with channel-specific prompts
        graph_admin = GraphAdmin(
            graph_service=self._graph_service,
            channel_id=channel_id,
            user_id=user_id,
            llm_config=llm_config,
            system_prompt=prompts["graph_admin"],
        )

        architect = SoftwareArchitect(
            llm_config=llm_config,
            system_prompt=prompts["architect"],
        )
        pm = ProductManager(
            llm_config=llm_config,
            system_prompt=prompts["pm"],
        )

        # Create group chat
        group_chat = autogen.GroupChat(
            agents=[pm.agent, architect.agent, graph_admin.agent],
            messages=[],
            max_round=10,
            speaker_selection_method="auto",
        )

        manager = autogen.GroupChatManager(
            groupchat=group_chat,
            llm_config=llm_config,
        )

        return {
            "graph_admin": graph_admin,
            "architect": architect,
            "pm": pm,
            "group_chat": group_chat,
            "manager": manager,
            "channel_id": channel_id,
            "message_history": [],
        }

    async def process_message(
        self,
        channel_id: str,
        user_id: str,
        message: str,
    ) -> dict:
        """
        Process a user message through the agent pipeline.

        Args:
            channel_id: Slack channel ID.
            user_id: Slack user ID.
            message: User message text.

        Returns:
            Dict with response and graph state.
        """
        logger.info(
            "processing_message",
            channel_id=channel_id,
            user_id=user_id,
            message_length=len(message),
        )

        session = self.get_or_create_session(channel_id, user_id)

        # Get current graph context
        graph = self._graph_service.get_or_create_graph(channel_id)

        # Check if summarization needed
        if self._summarization_service.needs_summarization(graph):
            logger.info("summarizing_context", channel_id=channel_id)
            await self._summarization_service.summarize_graph(graph)

        # Build context-injected prompt
        graph_context = graph.to_context_string()
        full_prompt = CONTEXT_INJECTION_TEMPLATE.format(
            graph_context=graph_context,
            user_message=message,
        )

        # Store message in history
        session["message_history"].append({
            "role": "user",
            "content": message,
        })

        # Initiate group chat
        try:
            # Start with PM analyzing the requirement
            pm_agent = session["pm"].agent
            manager = session["manager"]

            # Run the conversation
            await pm_agent.a_initiate_chat(
                manager,
                message=full_prompt,
                clear_history=False,
            )

            # Extract results
            chat_messages = session["group_chat"].messages
            response = self._extract_response(chat_messages)

            # Get updated graph state
            graph_state = self._graph_service.get_graph_state(channel_id)

            logger.info(
                "message_processed",
                channel_id=channel_id,
                response_length=len(response),
                nodes=graph_state["metrics"]["total_nodes"],
            )

            return {
                "response": response,
                "graph_state": graph_state,
                "chat_history": chat_messages,
            }

        except Exception as e:
            logger.error("agent_error", channel_id=channel_id, error=str(e))
            return {
                "response": f"Error processing request: {str(e)}",
                "graph_state": self._graph_service.get_graph_state(channel_id),
                "error": str(e),
            }

    def _extract_response(self, chat_messages: list) -> str:
        """
        Extract a user-friendly response from chat history.

        Args:
            chat_messages: List of chat messages from group chat.

        Returns:
            Consolidated response for the user.
        """
        # Find the last substantive message that's not a tool call
        for msg in reversed(chat_messages):
            content = msg.get("content", "")
            if content and not content.startswith("{") and msg.get("name") != "GraphAdmin":
                return content

        # Fallback: summarize what was done
        graph_admin_actions = [
            msg for msg in chat_messages
            if msg.get("name") == "GraphAdmin"
        ]

        if graph_admin_actions:
            return f"Processed your request. {len(graph_admin_actions)} graph operations performed."

        return "Request processed."

    def clear_session(self, channel_id: str) -> bool:
        """
        Clear a session for a channel.

        Args:
            channel_id: Slack channel ID.

        Returns:
            True if session was cleared.
        """
        if channel_id in self._sessions:
            del self._sessions[channel_id]
            return True
        return False

    def get_session_summary(self, channel_id: str) -> dict | None:
        """
        Get summary of a session.

        Args:
            channel_id: Slack channel ID.

        Returns:
            Session summary or None if not found.
        """
        if channel_id not in self._sessions:
            return None

        session = self._sessions[channel_id]
        return {
            "channel_id": channel_id,
            "message_count": len(session["message_history"]),
            "graph_summary": session["graph_admin"].get_graph_summary(),
        }
