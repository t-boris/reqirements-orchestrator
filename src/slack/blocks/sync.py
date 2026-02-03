"""Slack blocks for Jira sync UI."""

from typing import Any

from src.jira.models import FieldOwnership, SyncDiscrepancy
from src.jira.reconciliation import ReconciliationReport, ResolutionChoice


def build_sync_report_blocks(report: ReconciliationReport) -> list[dict[str, Any]]:
    """Build blocks for sync status report.

    Args:
        report: Reconciliation report

    Returns:
        Slack blocks
    """
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Jira Sync Status"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": report.summary,
            },
        },
    ]

    if report.has_discrepancies:
        blocks.append({
            "type": "divider",
        })
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Discrepancies found:*",
            },
        })

        # Group discrepancies by entity
        by_entity: dict[str, list[SyncDiscrepancy]] = {}
        for d in report.discrepancies:
            if d.entity_id not in by_entity:
                by_entity[d.entity_id] = []
            by_entity[d.entity_id].append(d)

        for entity_id, discrepancies in list(by_entity.items())[:5]:  # Limit to 5 entities
            jira_key = discrepancies[0].jira_key
            fields_text = "\n".join(
                f"- *{d.field}*: Slack=`{d.slack_value}` vs Jira=`{d.jira_value}`"
                for d in discrepancies
            )

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{jira_key}* (entity: {entity_id[:8]}...)\n{fields_text}",
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Resolve"},
                    "action_id": f"resolve_discrepancy_{entity_id}",
                    "value": entity_id,
                },
            })

        if len(by_entity) > 5:
            blocks.append({
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_...and {len(by_entity) - 5} more entities with discrepancies_",
                    }
                ],
            })

    else:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":white_check_mark: All committed entities match Jira",
            },
        })

    return blocks


def build_discrepancy_resolution_blocks(
    entity_id: str,
    jira_key: str,
    discrepancies: list[SyncDiscrepancy],
) -> list[dict[str, Any]]:
    """Build blocks for resolving a specific entity's discrepancies.

    Args:
        entity_id: Entity being resolved
        jira_key: Jira issue key
        discrepancies: Discrepancies for this entity

    Returns:
        Slack blocks with resolution buttons
    """
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Resolve: {jira_key}"},
        },
    ]

    for d in discrepancies:
        ownership_label = {
            FieldOwnership.JIRA_OWNED: ":jira: Jira-owned",
            FieldOwnership.SLACK_OWNED: ":slack: Slack-owned",
            FieldOwnership.SHARED: ":arrows_counterclockwise: Shared",
        }.get(d.ownership, "Unknown")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{d.field}* ({ownership_label})\n"
                    f"Slack says: `{d.slack_value}`\n"
                    f"Jira says: `{d.jira_value}`"
                ),
            },
        })

    # Resolution buttons
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Use Jira Values"},
                "action_id": "resolve_use_jira",
                "value": entity_id,
                "style": "primary",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Keep Slack Values"},
                "action_id": "resolve_keep_slack",
                "value": entity_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Skip"},
                "action_id": "resolve_skip",
                "value": entity_id,
            },
        ],
    })

    return blocks


def build_refresh_button(entity_id: str, jira_key: str) -> dict[str, Any]:
    """Build 'Refresh from Jira' button for entity card.

    Args:
        entity_id: Entity ID
        jira_key: Jira issue key

    Returns:
        Slack button element
    """
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": f"Refresh from {jira_key}"},
        "action_id": "refresh_from_jira",
        "value": f"{entity_id}:{jira_key}",
    }
