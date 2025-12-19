"""
Slack Formatter - Formats responses for Slack.

Converts graph data and agent responses to Slack Block Kit format.
"""

from typing import Any

from src.core.graph.models import NodeStatus


class SlackFormatter:
    """
    Formats messages for Slack using Block Kit.

    Provides rich formatting for:
    - Agent responses
    - Graph status
    - Metrics dashboards
    """

    def __init__(self, dashboard_url: str = "") -> None:
        """
        Initialize formatter.

        Args:
            dashboard_url: Base URL for the web dashboard.
        """
        self._dashboard_url = dashboard_url

    def format_response(self, result: dict) -> dict:
        """
        Format agent response for Slack.

        Args:
            result: Result from agent orchestrator.

        Returns:
            Dict with text and optional blocks.
        """
        response_text = result.get("response", "Request processed.")
        graph_state = result.get("graph_state", {})
        metrics = graph_state.get("metrics", {})

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": response_text,
                },
            },
        ]

        # Add metrics summary if nodes exist
        if metrics.get("total_nodes", 0) > 0:
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": self._format_metrics_inline(metrics),
                    },
                ],
            })

        # Add dashboard link if configured
        if self._dashboard_url:
            channel_id = graph_state.get("channel_id", "")
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "View Dashboard",
                        },
                        "url": f"{self._dashboard_url}/graph/{channel_id}",
                    },
                ],
            })

        return {
            "text": response_text,
            "blocks": blocks,
        }

    def format_status(self, state: dict) -> dict:
        """
        Format graph status for /req-status command.

        Args:
            state: Graph state from graph service.

        Returns:
            Dict with text and blocks.
        """
        metrics = state.get("metrics", {})
        nodes = state.get("nodes", [])

        # Count by status
        status_counts = {}
        type_counts = {}
        for node in nodes:
            status = node.get("status", "draft")
            node_type = node.get("type", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            type_counts[node_type] = type_counts.get(node_type, 0) + 1

        # Build status text
        status_emoji = {
            "draft": ":pencil2:",
            "approved": ":white_check_mark:",
            "synced": ":rocket:",
            "partially_synced": ":warning:",
            "conflict": ":x:",
        }

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Requirements Graph Status",
                },
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*Metrics*",
                },
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Total Nodes:* {metrics.get('total_nodes', 0)}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Total Edges:* {metrics.get('total_edges', 0)}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Completeness:* {metrics.get('completeness_score', 0):.1f}%",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Orphans:* {metrics.get('orphan_count', 0)}",
                    },
                ],
            },
        ]

        # Add status breakdown if nodes exist
        if status_counts:
            status_text = "\n".join([
                f"{status_emoji.get(s, ':grey_question:')} *{s.title()}:* {c}"
                for s, c in sorted(status_counts.items())
            ])
            blocks.append({"type": "divider"})
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*By Status*\n{status_text}",
                },
            })

        # Add type breakdown
        if type_counts:
            type_text = " | ".join([
                f"{t.title()}: {c}"
                for t, c in sorted(type_counts.items())
            ])
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"*By Type:* {type_text}",
                    },
                ],
            })

        # Add dashboard link
        if self._dashboard_url:
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Open Dashboard",
                        },
                        "url": f"{self._dashboard_url}/graph/{state.get('channel_id', '')}",
                        "style": "primary",
                    },
                ],
            })

        text = f"Graph has {metrics.get('total_nodes', 0)} nodes, {metrics.get('completeness_score', 0):.1f}% complete"

        return {
            "text": text,
            "blocks": blocks,
        }

    def _format_metrics_inline(self, metrics: dict) -> str:
        """Format metrics as inline text."""
        parts = [
            f":chart_with_upwards_trend: Nodes: {metrics.get('total_nodes', 0)}",
            f"Completeness: {metrics.get('completeness_score', 0):.1f}%",
        ]

        if metrics.get("orphan_count", 0) > 0:
            parts.append(f":warning: Orphans: {metrics['orphan_count']}")

        if metrics.get("conflict_ratio", 0) > 0:
            parts.append(f":x: Conflicts: {metrics['conflict_ratio']:.1f}%")

        return " | ".join(parts)

    def format_sync_result(self, result: dict) -> dict:
        """
        Format sync result for Slack.

        Args:
            result: Sync result from Jira adapter.

        Returns:
            Dict with text and blocks.
        """
        success = result.get("success", False)
        synced = result.get("synced_items", [])
        failed = result.get("failed_items", [])

        if success:
            emoji = ":white_check_mark:"
            text = f"Successfully synced {len(synced)} items to Jira"
        else:
            emoji = ":warning:"
            text = f"Partial sync: {len(synced)} succeeded, {len(failed)} failed"

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{emoji} {text}",
                },
            },
        ]

        # List synced items
        if synced:
            synced_text = "\n".join([
                f"• `{item['node_id']}` -> <{item.get('url', '#')}|{item.get('external_id', 'N/A')}>"
                for item in synced[:10]  # Limit to 10
            ])
            if len(synced) > 10:
                synced_text += f"\n_...and {len(synced) - 10} more_"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Synced:*\n{synced_text}",
                },
            })

        # List failed items
        if failed:
            failed_text = "\n".join([
                f"• `{item['node_id']}`: {item.get('error', 'Unknown error')}"
                for item in failed[:5]
            ])
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Failed:*\n{failed_text}",
                },
            })

        return {
            "text": text,
            "blocks": blocks,
        }
