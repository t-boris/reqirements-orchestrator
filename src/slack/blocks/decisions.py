"""Block builders for decision-related modals and views."""

import json
import time
from typing import Any


# Decision type options matching domain DecisionType enum values
DECISION_TYPE_OPTIONS = [
    {"text": {"type": "plain_text", "text": "Architecture"}, "value": "architecture"},
    {"text": {"type": "plain_text", "text": "Technology"}, "value": "technology"},
    {"text": {"type": "plain_text", "text": "Process"}, "value": "process"},
    {"text": {"type": "plain_text", "text": "Scope"}, "value": "scope"},
    {"text": {"type": "plain_text", "text": "Constraint"}, "value": "constraint"},
    {"text": {"type": "plain_text", "text": "Priority"}, "value": "priority"},
    {"text": {"type": "plain_text", "text": "Structure"}, "value": "structure"},
]


STATUS_BADGES: dict[str, str] = {
    "draft": ":pencil2: Draft",
    "proposed": ":hourglass: Proposed for Approval",
    "approved": ":white_check_mark: Approved",
    "committed": ":white_check_mark: Committed",
    "deprecated": ":no_entry_sign: Deprecated",
}


def _build_lifecycle_buttons(status: str, entity_id: str) -> list[dict[str, Any]]:
    """Build lifecycle action buttons appropriate for the given status.

    Args:
        status: Current lifecycle status (draft, proposed, approved, committed, deprecated).
        entity_id: Entity ID passed as button value.

    Returns:
        List of button elements, or empty list for deprecated status.
    """
    if status == "draft":
        return [{
            "type": "button",
            "text": {"type": "plain_text", "text": "Propose for Approval"},
            "style": "primary",
            "action_id": "adr_propose",
            "value": entity_id,
        }]
    elif status == "proposed":
        return [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve"},
                "style": "primary",
                "action_id": "adr_approve",
                "value": entity_id,
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Object"},
                "action_id": "adr_object",
                "value": entity_id,
            },
        ]
    elif status in ("approved", "committed"):
        return [{
            "type": "button",
            "text": {"type": "plain_text", "text": "Deprecate"},
            "style": "danger",
            "action_id": "adr_deprecate",
            "value": entity_id,
        }]
    # deprecated or unknown: no buttons
    return []


def build_adr_post_blocks(
    title: str,
    decision_type: str,
    decision: str,
    rationale: str,
    alternatives: list[str] | None = None,
    patterns_referenced: list[str] | None = None,
    tradeoffs: list[str] | None = None,
    recorded_by: str | None = None,
    status: str = "draft",
    entity_id: str | None = None,
) -> list[dict[str, Any]]:
    """Build blocks for a pinned ADR channel post.

    This is the formatted message posted to the channel when a decision is recorded.
    Includes a status badge and lifecycle action buttons when entity_id is provided.
    """
    now = int(time.time())
    badge = STATUS_BADGES.get(status, STATUS_BADGES["draft"])

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f":memo: *ADR: {title}*"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Type: {decision_type} | Status: {badge}"}],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": decision},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"_Rationale: {rationale}_"},
        },
    ]

    if alternatives:
        alts_text = ", ".join(alternatives)
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_Alternatives: {alts_text}_"}],
        })

    if patterns_referenced:
        patterns_text = ", ".join(patterns_referenced)
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_Patterns: {patterns_text}_"}],
        })

    if tradeoffs:
        tradeoff_items = "\n".join(f"  \u2022 {t}" for t in tradeoffs)
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Tradeoffs:*\n{tradeoff_items}"},
        })

    # Lifecycle action buttons (only if entity_id provided)
    if entity_id:
        buttons = _build_lifecycle_buttons(status, entity_id)
        if buttons:
            blocks.append({
                "type": "actions",
                "elements": buttons,
            })

    blocks.append({"type": "divider"})

    footer_parts = []
    if recorded_by:
        footer_parts.append(f"Recorded by <@{recorded_by}>")
    footer_parts.append(f"<!date^{now}^{{date_short}} {{time}}|now>")
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": " | ".join(footer_parts)}],
    })

    return blocks


def build_edit_adr_modal(
    adr_index: int,
    decision: dict,
    channel_id: str,
    message_ts: str,
    thread_ts: str | None,
) -> dict:
    """Build a Slack modal for editing a single ADR.

    Args:
        adr_index: 0-based index of the ADR in the preview message.
        decision: Dict with title, decision_type, decision, rationale, alternatives_considered.
        channel_id: Channel where the preview message lives.
        message_ts: Timestamp of the preview message.
        thread_ts: Thread timestamp (if in a thread).
    """
    private_metadata = json.dumps({
        "adr_index": adr_index,
        "channel_id": channel_id,
        "message_ts": message_ts,
        "thread_ts": thread_ts,
    })

    # Find the matching initial option for decision_type
    dt_value = decision.get("decision_type", "architecture").lower()
    initial_option = next(
        (opt for opt in DECISION_TYPE_OPTIONS if opt["value"] == dt_value),
        DECISION_TYPE_OPTIONS[0],
    )

    alts_text = ", ".join(decision.get("alternatives_considered", []))

    return {
        "type": "modal",
        "callback_id": "edit_adr_modal",
        "private_metadata": private_metadata,
        "title": {"type": "plain_text", "text": "Edit Decision"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": "title_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "title_input",
                    "initial_value": decision.get("title", ""),
                    "placeholder": {"type": "plain_text", "text": "Decision title"},
                },
                "label": {"type": "plain_text", "text": "Title"},
            },
            {
                "type": "input",
                "block_id": "type_block",
                "element": {
                    "type": "static_select",
                    "action_id": "type_select",
                    "options": DECISION_TYPE_OPTIONS,
                    "initial_option": initial_option,
                },
                "label": {"type": "plain_text", "text": "Decision Type"},
            },
            {
                "type": "input",
                "block_id": "decision_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "decision_input",
                    "multiline": True,
                    "initial_value": decision.get("decision", ""),
                    "placeholder": {"type": "plain_text", "text": "What was decided"},
                },
                "label": {"type": "plain_text", "text": "Decision"},
            },
            {
                "type": "input",
                "block_id": "rationale_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "rationale_input",
                    "multiline": True,
                    "initial_value": decision.get("rationale", ""),
                    "placeholder": {"type": "plain_text", "text": "Why this decision was made"},
                },
                "label": {"type": "plain_text", "text": "Rationale"},
            },
            {
                "type": "input",
                "block_id": "alternatives_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "alternatives_input",
                    "initial_value": alts_text,
                    "placeholder": {"type": "plain_text", "text": "Comma-separated alternatives"},
                },
                "label": {"type": "plain_text", "text": "Alternatives Considered"},
            },
        ],
    }
