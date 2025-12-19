"""
Agent Tools - Functions available to AutoGen agents for graph manipulation.

These tools are registered with the GraphAdmin agent and executed
when called by other agents in the group chat.
"""

import json
from typing import Any, Callable

from src.core.graph.models import EdgeType, NodeType
from src.core.services.graph_service import GraphService


def create_agent_tools(
    graph_service: GraphService,
    channel_id: str,
    user_id: str,
) -> dict[str, Callable]:
    """
    Create tool functions bound to a specific graph context.

    Args:
        graph_service: The graph service instance.
        channel_id: Slack channel ID.
        user_id: Slack user ID for attribution.

    Returns:
        Dictionary of tool name -> callable function.
    """

    def add_node(
        node_type: str,
        title: str,
        description: str = "",
        **attributes: Any,
    ) -> str:
        """
        Add a new node to the requirements graph.

        Args:
            node_type: Type of node (goal, epic, story, subtask, component, constraint, risk, question, context)
            title: Human-readable title for the node
            description: Detailed description of the requirement
            **attributes: Additional attributes (acceptance_criteria, actor, priority, etc.)

        Returns:
            JSON string with created node info.
        """
        try:
            node = graph_service.add_node(
                channel_id=channel_id,
                user_id=user_id,
                node_type=NodeType(node_type.lower()),
                title=title,
                description=description,
                **attributes,
            )
            return json.dumps({
                "success": True,
                "node_id": node.id,
                "type": node.type.value,
                "title": node.title,
            })
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    def update_node(node_id: str, **changes: Any) -> str:
        """
        Update an existing node in the graph.

        Args:
            node_id: ID of the node to update
            **changes: Fields to update (title, description, status, attributes)

        Returns:
            JSON string with update result.
        """
        try:
            node = graph_service.update_node(
                channel_id=channel_id,
                user_id=user_id,
                node_id=node_id,
                **changes,
            )
            return json.dumps({
                "success": True,
                "node_id": node.id,
                "updated_fields": list(changes.keys()),
            })
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    def delete_node(node_id: str) -> str:
        """
        Delete a node from the graph.

        Args:
            node_id: ID of the node to delete

        Returns:
            JSON string with deletion result.
        """
        try:
            result = graph_service.delete_node(
                channel_id=channel_id,
                user_id=user_id,
                node_id=node_id,
            )
            return json.dumps({"success": result, "node_id": node_id})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    def add_edge(
        source_id: str,
        target_id: str,
        edge_type: str,
        **attributes: Any,
    ) -> str:
        """
        Add a relationship between two nodes.

        Args:
            source_id: Source node ID
            target_id: Target node ID
            edge_type: Type of relationship (decomposes_to, depends_on, requires_component, constrained_by, conflicts_with, mitigates, blocks)
            **attributes: Additional edge attributes

        Returns:
            JSON string with created edge info.
        """
        try:
            edge = graph_service.add_edge(
                channel_id=channel_id,
                user_id=user_id,
                source_id=source_id,
                target_id=target_id,
                edge_type=EdgeType(edge_type.lower()),
                **attributes,
            )
            return json.dumps({
                "success": True,
                "source_id": edge.source_id,
                "target_id": edge.target_id,
                "type": edge.type.value,
            })
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    def delete_edge(source_id: str, target_id: str) -> str:
        """
        Delete a relationship between two nodes.

        Args:
            source_id: Source node ID
            target_id: Target node ID

        Returns:
            JSON string with deletion result.
        """
        try:
            result = graph_service.delete_edge(
                channel_id=channel_id,
                user_id=user_id,
                source_id=source_id,
                target_id=target_id,
            )
            return json.dumps({"success": result})
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    def get_graph_state() -> str:
        """
        Get the current state of the requirements graph.

        Returns:
            JSON string with nodes, edges, and metrics.
        """
        try:
            state = graph_service.get_graph_state(channel_id)
            return json.dumps(state, default=str)
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    def validate_graph() -> str:
        """
        Validate the graph and return any issues.

        Returns:
            JSON string with validation results (orphans, conflicts, etc.)
        """
        try:
            issues = graph_service.validate_graph(channel_id)
            has_issues = any(issues.values())
            return json.dumps({
                "valid": not has_issues,
                "issues": issues,
            })
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    return {
        "add_node": add_node,
        "update_node": update_node,
        "delete_node": delete_node,
        "add_edge": add_edge,
        "delete_edge": delete_edge,
        "get_graph_state": get_graph_state,
        "validate_graph": validate_graph,
    }


# OpenAI function definitions for tool calling
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "add_node",
            "description": "Add a new node to the requirements graph",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_type": {
                        "type": "string",
                        "enum": ["goal", "epic", "story", "subtask", "component", "constraint", "risk", "question", "context"],
                        "description": "Type of node to create",
                    },
                    "title": {
                        "type": "string",
                        "description": "Human-readable title for the node",
                    },
                    "description": {
                        "type": "string",
                        "description": "Detailed description of the requirement",
                    },
                    "acceptance_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of acceptance criteria (for stories)",
                    },
                    "actor": {
                        "type": "string",
                        "description": "User role/actor (for stories)",
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                        "description": "Priority level",
                    },
                    "tech_stack": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Technologies involved (for components/subtasks)",
                    },
                },
                "required": ["node_type", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_node",
            "description": "Update an existing node in the graph",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "ID of the node to update",
                    },
                    "title": {
                        "type": "string",
                        "description": "New title",
                    },
                    "description": {
                        "type": "string",
                        "description": "New description",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["draft", "approved", "synced", "partially_synced", "conflict"],
                        "description": "New status",
                    },
                },
                "required": ["node_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_node",
            "description": "Delete a node from the graph",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {
                        "type": "string",
                        "description": "ID of the node to delete",
                    },
                },
                "required": ["node_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_edge",
            "description": "Add a relationship between two nodes",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source node ID",
                    },
                    "target_id": {
                        "type": "string",
                        "description": "Target node ID",
                    },
                    "edge_type": {
                        "type": "string",
                        "enum": ["decomposes_to", "depends_on", "requires_component", "constrained_by", "conflicts_with", "mitigates", "blocks"],
                        "description": "Type of relationship",
                    },
                },
                "required": ["source_id", "target_id", "edge_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_edge",
            "description": "Delete a relationship between two nodes",
            "parameters": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "Source node ID",
                    },
                    "target_id": {
                        "type": "string",
                        "description": "Target node ID",
                    },
                },
                "required": ["source_id", "target_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_graph_state",
            "description": "Get the current state of the requirements graph including all nodes, edges, and metrics",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_graph",
            "description": "Validate the graph and return any issues like orphan nodes, conflicts, or missing relationships",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]
