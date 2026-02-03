"""Block builders for decision-related modals and views."""

import json


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
