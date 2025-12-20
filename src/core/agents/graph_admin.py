"""
Graph Admin Agent - Executor for graph operations.

This agent implements the UserProxy pattern from AutoGen,
executing tool calls made by expert agents (PM, Architect).
"""

import json
from typing import Any, Callable

import autogen

from src.core.agents.prompts import GRAPH_ADMIN_PROMPT
from src.core.agents.tools import TOOL_DEFINITIONS, create_agent_tools
from src.core.services.graph_service import GraphService


class GraphAdmin:
    """
    Graph Admin agent - executes graph operations.

    Acts as a UserProxy in the AutoGen GroupChat, executing tool calls
    from the PM and Architect agents. Does not make autonomous decisions.
    """

    def __init__(
        self,
        graph_service: GraphService,
        channel_id: str,
        user_id: str,
        llm_config: dict | None = None,
        system_prompt: str | None = None,
    ) -> None:
        """
        Initialize Graph Admin agent.

        Args:
            graph_service: Service for graph operations.
            channel_id: Slack channel ID.
            user_id: Slack user ID for attribution.
            llm_config: AutoGen LLM configuration.
            system_prompt: Custom system prompt (uses default if None).
        """
        self._graph_service = graph_service
        self._channel_id = channel_id
        self._user_id = user_id

        # Create bound tool functions
        self._tools = create_agent_tools(graph_service, channel_id, user_id)

        # Use custom prompt or default
        prompt = system_prompt if system_prompt else GRAPH_ADMIN_PROMPT

        # Create AutoGen agent
        self._agent = autogen.UserProxyAgent(
            name="GraphAdmin",
            system_message=prompt,
            human_input_mode="NEVER",
            code_execution_config=False,
            llm_config=llm_config,
        )

        # Register tool functions
        self._register_tools()

    def _register_tools(self) -> None:
        """Register tool functions with the agent."""
        for name, func in self._tools.items():
            self._agent.register_function(
                function_map={name: func}
            )

    @property
    def agent(self) -> autogen.UserProxyAgent:
        """Get the underlying AutoGen agent."""
        return self._agent

    @property
    def tools(self) -> dict[str, Callable]:
        """Get the registered tools."""
        return self._tools

    def execute_tool(self, tool_name: str, **kwargs: Any) -> str:
        """
        Execute a tool by name.

        Args:
            tool_name: Name of the tool to execute.
            **kwargs: Tool arguments.

        Returns:
            JSON string with execution result.
        """
        if tool_name not in self._tools:
            return json.dumps({
                "success": False,
                "error": f"Unknown tool: {tool_name}",
            })

        try:
            return self._tools[tool_name](**kwargs)
        except Exception as e:
            return json.dumps({
                "success": False,
                "error": str(e),
            })

    def get_graph_summary(self) -> str:
        """
        Get a summary of the current graph state.

        Returns:
            Human-readable graph summary.
        """
        state = self._graph_service.get_graph_state(self._channel_id)
        metrics = state.get("metrics", {})

        lines = [
            f"Nodes: {metrics.get('total_nodes', 0)}",
            f"Edges: {metrics.get('total_edges', 0)}",
            f"Completeness: {metrics.get('completeness_score', 0):.1f}%",
            f"Orphans: {metrics.get('orphan_count', 0)}",
            f"Conflicts: {metrics.get('conflict_ratio', 0):.1f}%",
        ]

        return " | ".join(lines)
