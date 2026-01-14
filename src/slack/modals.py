"""Slack modal view builders for interactive forms.

Modals are opened in response to button clicks and closed on submit/cancel.
"""
import json
from typing import Optional

from src.schemas.draft import TicketDraft


def build_edit_draft_modal(
    draft: TicketDraft,
    session_id: str,
    draft_hash: str,
    preview_message_ts: str,
) -> dict:
    """Build modal view for editing draft fields.

    All draft fields are editable:
    - Title: plain_text_input (required)
    - Problem: plain_text_input multiline (required)
    - Proposed Solution: plain_text_input multiline (optional)
    - Acceptance Criteria: plain_text_input multiline (one per line)
    - Constraints: plain_text_input multiline (optional, key=value format)
    - Risks: plain_text_input multiline (optional)

    Args:
        draft: Current TicketDraft to pre-fill values
        session_id: Session ID for identifying the session
        draft_hash: Hash of draft for version checking
        preview_message_ts: Message timestamp of the preview to update

    Returns:
        Slack modal view structure
    """
    # Build private_metadata with session info
    private_metadata = json.dumps({
        "session_id": session_id,
        "draft_hash": draft_hash,
        "preview_message_ts": preview_message_ts,
    })

    # Build blocks for each field
    blocks = []

    # Title (required)
    blocks.append({
        "type": "input",
        "block_id": "title_block",
        "label": {
            "type": "plain_text",
            "text": "Title",
        },
        "element": {
            "type": "plain_text_input",
            "action_id": "title_input",
            "placeholder": {
                "type": "plain_text",
                "text": "Brief title for the ticket",
            },
            "initial_value": draft.title or "",
        },
    })

    # Problem (required)
    blocks.append({
        "type": "input",
        "block_id": "problem_block",
        "label": {
            "type": "plain_text",
            "text": "Problem",
        },
        "element": {
            "type": "plain_text_input",
            "action_id": "problem_input",
            "multiline": True,
            "placeholder": {
                "type": "plain_text",
                "text": "What problem are we solving?",
            },
            "initial_value": draft.problem or "",
        },
    })

    # Proposed Solution (optional)
    blocks.append({
        "type": "input",
        "block_id": "solution_block",
        "label": {
            "type": "plain_text",
            "text": "Proposed Solution",
        },
        "element": {
            "type": "plain_text_input",
            "action_id": "solution_input",
            "multiline": True,
            "placeholder": {
                "type": "plain_text",
                "text": "How should we solve it? (optional)",
            },
            "initial_value": draft.proposed_solution or "",
        },
        "optional": True,
    })

    # Acceptance Criteria (one per line)
    ac_text = "\n".join(draft.acceptance_criteria) if draft.acceptance_criteria else ""
    blocks.append({
        "type": "input",
        "block_id": "acceptance_criteria_block",
        "label": {
            "type": "plain_text",
            "text": "Acceptance Criteria",
        },
        "hint": {
            "type": "plain_text",
            "text": "One criterion per line",
        },
        "element": {
            "type": "plain_text_input",
            "action_id": "acceptance_criteria_input",
            "multiline": True,
            "placeholder": {
                "type": "plain_text",
                "text": "How will we know this is done?",
            },
            "initial_value": ac_text,
        },
        "optional": True,
    })

    # Constraints (key=value format)
    constraints_text = ""
    if draft.constraints:
        constraints_text = "\n".join(
            f"{c.key}={c.value}" for c in draft.constraints
        )
    blocks.append({
        "type": "input",
        "block_id": "constraints_block",
        "label": {
            "type": "plain_text",
            "text": "Constraints",
        },
        "hint": {
            "type": "plain_text",
            "text": "One per line, format: key=value",
        },
        "element": {
            "type": "plain_text_input",
            "action_id": "constraints_input",
            "multiline": True,
            "placeholder": {
                "type": "plain_text",
                "text": "e.g., API.format=JSON",
            },
            "initial_value": constraints_text,
        },
        "optional": True,
    })

    # Risks (optional)
    risks_text = "\n".join(draft.risks) if draft.risks else ""
    blocks.append({
        "type": "input",
        "block_id": "risks_block",
        "label": {
            "type": "plain_text",
            "text": "Risks",
        },
        "hint": {
            "type": "plain_text",
            "text": "One risk per line",
        },
        "element": {
            "type": "plain_text_input",
            "action_id": "risks_input",
            "multiline": True,
            "placeholder": {
                "type": "plain_text",
                "text": "What could go wrong?",
            },
            "initial_value": risks_text,
        },
        "optional": True,
    })

    return {
        "type": "modal",
        "callback_id": "edit_draft_modal",
        "title": {
            "type": "plain_text",
            "text": "Edit Draft",
        },
        "submit": {
            "type": "plain_text",
            "text": "Update",
        },
        "close": {
            "type": "plain_text",
            "text": "Cancel",
        },
        "private_metadata": private_metadata,
        "blocks": blocks,
    }


def parse_modal_values(view_state: dict) -> dict:
    """Parse submitted values from modal view state.

    Args:
        view_state: The view.state.values from modal submission

    Returns:
        Dict with parsed field values
    """
    values = {}

    # Extract each field from view state
    if "title_block" in view_state:
        values["title"] = view_state["title_block"]["title_input"]["value"] or ""

    if "problem_block" in view_state:
        values["problem"] = view_state["problem_block"]["problem_input"]["value"] or ""

    if "solution_block" in view_state:
        values["proposed_solution"] = (
            view_state["solution_block"]["solution_input"]["value"] or ""
        )

    if "acceptance_criteria_block" in view_state:
        ac_raw = view_state["acceptance_criteria_block"]["acceptance_criteria_input"]["value"] or ""
        # Parse as list (split by newlines, filter empty)
        values["acceptance_criteria"] = [
            line.strip() for line in ac_raw.split("\n") if line.strip()
        ]

    if "constraints_block" in view_state:
        constraints_raw = view_state["constraints_block"]["constraints_input"]["value"] or ""
        # Parse as key=value pairs
        constraints = []
        for line in constraints_raw.split("\n"):
            line = line.strip()
            if "=" in line:
                key, value = line.split("=", 1)
                constraints.append({"key": key.strip(), "value": value.strip()})
        values["constraints_raw"] = constraints

    if "risks_block" in view_state:
        risks_raw = view_state["risks_block"]["risks_input"]["value"] or ""
        # Parse as list (split by newlines, filter empty)
        values["risks"] = [
            line.strip() for line in risks_raw.split("\n") if line.strip()
        ]

    return values
