"""Decision card blocks for Slack UI.

Four visual states matching psychological weight (from CONTEXT.md):
1. Draft/Discussion mode -> Compact inline card (lightweight, tentative)
2. Approval moment -> Full decision block (heavy, "are you sure?")
3. Approved -> Compact but authoritative (infrastructure, not conversational)
4. Commit log -> Ultra compact (pure signal)

Same object, four visual identities: idea -> proposal -> law -> record

Phase 41: Added build_impact_preview_card for decision change confirmation UI.
"""
import json
from typing import Optional

from src.schemas.decision import (
    ApplyResult,
    Decision,
    DecisionChangeOp,
    DecisionChangeOpType,
    DecisionStatus,
    DecisionType,
    ImpactSummary,
)


def build_rich_context_blocks(decision: Decision) -> list[dict]:
    """Build Slack blocks for decision rich context.

    Returns collapsible sections for rationale, context, alternatives, consequences.
    Empty list if no rich context.
    """
    if not decision.has_rich_context():
        return []

    blocks = []

    # Rationale section
    if decision.rationale:
        rationale_text = []
        for item in decision.rationale:
            prefix = "▸" if item.weight == "primary" else "•"
            rationale_text.append(f"{prefix} {item.text}")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Rationale:*\n" + "\n".join(rationale_text),
            },
        })

    # Context section
    if decision.context:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Context (before):*\n{decision.context}",
            },
        })

    # Alternatives section
    if decision.alternatives:
        alt_text = []
        for alt in decision.alternatives:
            alt_text.append(f"• *{alt.option}*")
            alt_text.append(f"  _Rejected: {alt.rejected_reason}_")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Alternatives Considered:*\n" + "\n".join(alt_text),
            },
        })

    # Consequences section
    if decision.consequences:
        cons_text = []
        for cons in decision.consequences:
            severity_emoji = {
                "minor": "🟢",
                "moderate": "🟡",
                "major": "🔴",
            }.get(cons.severity, "⚪")
            cons_text.append(f"{severity_emoji} *{cons.area}:* {cons.impact}")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Consequences:*\n" + "\n".join(cons_text),
            },
        })

    return blocks


def build_compact_draft_card(
    decision: Decision,
) -> list[dict]:
    """Build compact inline card for PROPOSED decision.

    Used during discussion when decision is fluid and tentative.
    Click expands to show full details.

    Format:
    {type_emoji} Proposed decision:
    {title}
    [Edit] [Approve] [Discard]
    """
    # Decision type emoji
    type_emoji = _get_type_emoji(decision.decision_type)

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{type_emoji} *Proposed decision:*\n{decision.title}",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit"},
                    "action_id": "decision_edit",
                    "value": json.dumps({
                        "decision_id": decision.id,
                        "version": decision.version,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": "decision_approve",
                    "value": json.dumps({
                        "decision_id": decision.id,
                        "version": decision.version,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Discard"},
                    "style": "danger",
                    "action_id": "decision_discard",
                    "value": json.dumps({
                        "decision_id": decision.id,
                        "version": decision.version,
                    }),
                },
            ],
        },
    ]

    return blocks


def build_approval_block(
    decision: Decision,
    linked_tickets: list[str] | None = None,
) -> list[dict]:
    """Build full decision block for approval moment.

    This is the "commit screen" — must feel heavy and formal.
    Shows what will happen when approved.

    Updated for Phase 40: Includes rich context sections when available.

    Format:
    ━━━━━━━━━━━━━━━━━━━━━━
    {type_emoji} Decision DEC-{id} ({type}) — Ready for approval

    Title:
    {title}

    Description:
    {description}

    [Rich context sections if available]

    Will update Jira:
    - SCRUM-123
    - SCRUM-456

    Version: v{version}
    Status: PROPOSED
    ━━━━━━━━━━━━━━━━━━━━━━

    [Approve decision]   [Edit]   [Cancel]
    """
    type_emoji = _get_type_emoji(decision.decision_type)
    type_label = decision.decision_type.value.upper()

    blocks = [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{type_emoji} *Decision DEC-{decision.id[:8]}* ({type_label}) — Ready for approval",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Title:*\n{decision.title}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Description:*\n{decision.description}",
            },
        },
    ]

    # Add rich context sections (Phase 40)
    rich_context_blocks = build_rich_context_blocks(decision)
    if rich_context_blocks:
        blocks.append({"type": "divider"})
        blocks.extend(rich_context_blocks)

    # Add Jira section if tickets linked
    if linked_tickets:
        jira_list = "\n".join(f"• {key}" for key in linked_tickets)
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Will update Jira:*\n{jira_list}",
            },
        })

    # Metadata
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"Version: v{decision.version} | Status: {decision.status.value.upper()}",
            },
        ],
    })

    blocks.append({"type": "divider"})

    # Action buttons
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Approve decision"},
                "style": "primary",
                "action_id": "decision_approve",
                "value": json.dumps({
                    "decision_id": decision.id,
                    "version": decision.version,
                }),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Edit"},
                "action_id": "decision_edit",
                "value": json.dumps({
                    "decision_id": decision.id,
                    "version": decision.version,
                }),
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "Cancel"},
                "action_id": "decision_cancel",
                "value": json.dumps({
                    "decision_id": decision.id,
                    "version": decision.version,
                }),
            },
        ],
    })

    return blocks


def build_approved_card(
    decision: Decision,
    linked_tickets: list[str] | None = None,
) -> list[dict]:
    """Build compact but authoritative card for APPROVED decision.

    No longer conversational — this is infrastructure.

    Updated for Phase 40: Shows rationale preview with [Show details] button.

    Format:
    {type_emoji} DEC-{id} v{version} ({type}) — Approved
    {title}
    {rationale_preview}
    Applies to: SCRUM-123, SCRUM-456
    [Change] [Deprecate] [Show details]
    """
    type_emoji = _get_type_emoji(decision.decision_type)
    type_label = decision.decision_type.value.upper()

    applies_to = ""
    if linked_tickets:
        applies_to = f"\n_Applies to: {', '.join(linked_tickets)}_"

    # Add rationale preview if available (Phase 40)
    rationale_preview = ""
    if decision.rationale:
        # Show first rationale item as preview
        first_rationale = decision.rationale[0].text
        if len(first_rationale) > 80:
            first_rationale = first_rationale[:80] + "..."
        more_count = len(decision.rationale) - 1
        more_text = f" (+{more_count} more)" if more_count > 0 else ""
        rationale_preview = f"\n_▸ {first_rationale}{more_text}_"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{type_emoji} *DEC-{decision.id[:8]}* v{decision.version} ({type_label}) — *Approved*\n"
                    f"{decision.title}{rationale_preview}{applies_to}"
                ),
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Change"},
                    "action_id": "decision_change",
                    "value": json.dumps({
                        "decision_id": decision.id,
                        "version": decision.version,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Deprecate"},
                    "action_id": "decision_deprecate",
                    "value": json.dumps({
                        "decision_id": decision.id,
                        "version": decision.version,
                    }),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Show details"},
                    "action_id": "decision_show_details",
                    "value": json.dumps({
                        "decision_id": decision.id,
                    }),
                },
            ],
        },
    ]

    return blocks


def build_decision_details_blocks(
    decision: Decision,
    linked_tickets: list[str] | None = None,
) -> list[dict]:
    """Build full decision details blocks for /maro decision show.

    Shows complete decision with all rich context fields.
    """
    type_emoji = _get_type_emoji(decision.decision_type)
    type_label = decision.decision_type.value.upper()
    status_emoji = "✅" if decision.status.value == "approved" else "📝"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{type_emoji} Decision DEC-{decision.id[:8]}",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Type:*\n{type_label}"},
                {"type": "mrkdwn", "text": f"*Status:*\n{status_emoji} {decision.status.value.upper()}"},
                {"type": "mrkdwn", "text": f"*Version:*\nv{decision.version}"},
                {"type": "mrkdwn", "text": f"*Created by:*\n<@{decision.created_by}>"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{decision.title}*\n\n{decision.description}",
            },
        },
    ]

    # Add rich context (Phase 40)
    rich_blocks = build_rich_context_blocks(decision)
    if rich_blocks:
        blocks.append({"type": "divider"})
        blocks.extend(rich_blocks)

    # Linked tickets
    if linked_tickets:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Linked Jira Tickets:*\n" + "\n".join(f"• {k}" for k in linked_tickets),
            },
        })

    return blocks


def build_commit_log_entry(
    decision: Decision,
    linked_tickets: list[str] | None = None,
    approved_by: str | None = None,
) -> list[dict]:
    """Build ultra-compact commit log entry for Channel Work Board.

    Pure signal, no fluff. Like git log.

    Format:
    {type_emoji} DEC-{id} v{version}
    + {type}: {title}
    Affects: SCRUM-123, SCRUM-456
    by @user
    """
    type_emoji = _get_type_emoji(decision.decision_type)
    type_label = decision.decision_type.value.capitalize()

    affects = ""
    if linked_tickets:
        affects = f"\nAffects: {', '.join(linked_tickets)}"

    by_user = ""
    if approved_by:
        by_user = f"\nby <@{approved_by}>"

    blocks = [
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": (
                        f"{type_emoji} *DEC-{decision.id[:8]}* v{decision.version}\n"
                        f"+ {type_label}: {decision.title}{affects}{by_user}"
                    ),
                },
            ],
        },
    ]

    return blocks


def build_deprecated_decision_blocks(
    decision: Decision,
    replacement: Decision | None = None,
) -> list[dict]:
    """Build blocks for deprecated decision.

    Message is not deleted — marked as historical with pointer.

    Format:
    {type_emoji} Decision DEC-{id} ({type})
    Status: DEPRECATED
    Replaced by: DEC-{replacement_id}

    [This decision is no longer active]
    """
    type_emoji = _get_type_emoji(decision.decision_type)
    type_label = decision.decision_type.value.upper()

    replacement_text = ""
    if replacement:
        replacement_text = f"\nReplaced by: DEC-{replacement.id[:8]}"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{type_emoji} *Decision DEC-{decision.id[:8]}* ({type_label})\n"
                    f"Status: *DEPRECATED*{replacement_text}"
                ),
            },
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "_This decision is no longer active_",
                },
            ],
        },
    ]

    return blocks


def _get_type_emoji(decision_type: DecisionType) -> str:
    """Get emoji for decision type."""
    return {
        DecisionType.ARCH: "🧠",        # Architecture
        DecisionType.SCOPE: "📐",       # Scope
        DecisionType.CONSTRAINT: "🔒",  # Constraint
        DecisionType.PRIORITY: "⚡",    # Priority
        DecisionType.STRUCTURE: "🏗️",   # Structure
        DecisionType.PROCESS: "⚙️",     # Process
    }.get(decision_type, "🧠")


def build_impact_preview_card(
    decision: Decision,
    op: DecisionChangeOp,
    impact: ImpactSummary,
) -> list[dict]:
    """Build impact preview card for decision change confirmation.

    Shows:
    - What operation is being performed
    - Which Jira tickets will be affected
    - Any conflicts detected
    - Confirmation buttons

    Phase 41: Decision Change Propagation - Confirmation UI

    Args:
        decision: The decision being changed
        op: The change operation with version info
        impact: Results of impact analysis

    Returns:
        List of Slack blocks for the impact preview card
    """
    blocks = []

    # Header based on operation
    if op.operation == DecisionChangeOpType.EDIT:
        header_text = f"Updating DEC-{decision.id[:8]} v{op.from_version} -> v{op.to_version}"
    elif op.operation == DecisionChangeOpType.DEPRECATE:
        header_text = f"Deprecating DEC-{decision.id[:8]}"
    else:  # DELETE
        header_text = f"Deleting DEC-{decision.id[:8]}"

    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": header_text}
    })

    # Decision title
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*{decision.title}*"}
    })

    blocks.append({"type": "divider"})

    # Impact summary
    impact_lines = []

    if impact.total_affected == 0:
        impact_lines.append("No Jira tickets linked to this decision.")
    else:
        impact_lines.append(f"Will update *{impact.total_affected}* Jira ticket(s) (managed sections only)")

        if impact.safe_count > 0:
            impact_lines.append(f"  - {impact.safe_count} already synced")
        if impact.pending_count > 0:
            impact_lines.append(f"  - {impact.pending_count} pending updates")
        if impact.conflict_count > 0:
            impact_lines.append(f"  - {impact.conflict_count} with conflicts")

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(impact_lines)}
    })

    # Conflict details if any
    if impact.conflict_count > 0:
        conflict_tickets = [t for t in impact.tickets if t.sync_status in ("conflict", "structural")]
        conflict_text = "*Conflicts detected:*\n"
        for t in conflict_tickets[:5]:  # Limit to 5
            conflict_text += f"- {t.jira_key}: {t.message or 'External changes detected'}\n"
        if len(conflict_tickets) > 5:
            conflict_text += f"- ...and {len(conflict_tickets) - 5} more\n"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": conflict_text}
        })

    # Warning for high risk
    if impact.risk_level == "high":
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "*High impact operation* - review carefully before proceeding"}]
        })

    blocks.append({"type": "divider"})

    # Buttons
    button_value = json.dumps({
        "op_id": op.id,
        "decision_id": decision.id,
    })

    buttons = []

    # Primary action - Apply updates (if there are Jira writes)
    if impact.has_jira_writes:
        buttons.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Apply updates"},
            "style": "primary",
            "action_id": "decision_change_apply",
            "value": button_value,
        })
        buttons.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Apply to Slack only"},
            "action_id": "decision_change_slack_only",
            "value": button_value,
        })
    else:
        # No Jira writes needed, just confirm
        buttons.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Confirm"},
            "style": "primary",
            "action_id": "decision_change_apply",
            "value": button_value,
        })

    buttons.append({
        "type": "button",
        "text": {"type": "plain_text", "text": "Cancel"},
        "action_id": "decision_change_cancel",
        "value": button_value,
    })

    blocks.append({"type": "actions", "elements": buttons})

    return blocks


def build_change_result_card(
    decision: Decision,
    op: DecisionChangeOp,
    result: ApplyResult,
) -> list[dict]:
    """Build result card after applying decision change.

    Shows what was updated, what failed, and retry options if needed.

    Phase 41-04: Transactional Apply + Result Card

    Args:
        decision: The decision that was changed
        op: The change operation that was executed
        result: Results of applying the change

    Returns:
        List of Slack blocks for the result card
    """
    blocks = []

    # Header with status
    if result.success:
        emoji = "white_check_mark"
        status = "complete"
    else:
        emoji = "warning"
        status = "completed with errors"

    blocks.append({
        "type": "header",
        "text": {"type": "plain_text", "text": f":{emoji}: Decision change {status}"}
    })

    # Decision info
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"*{decision.title}* (DEC-{decision.id[:8]})"}
    })

    # Results summary
    summary_lines = []
    if result.db_updated:
        summary_lines.append(":white_check_mark: Database updated")
    if result.slack_updated:
        summary_lines.append(":white_check_mark: Slack message updated")
    if result.jira_updated:
        summary_lines.append(f":white_check_mark: Jira updated ({result.updated_count} ticket(s))")
    elif result.total_tickets > 0:
        summary_lines.append(f":warning: Jira: {result.updated_count}/{result.total_tickets} updated")

    # If skipped Jira (slack-only mode)
    if result.total_tickets == 0 and result.db_updated:
        summary_lines.append(":white_circle: Jira sync skipped (no tickets or slack-only)")

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(summary_lines)}
    })

    # Failed tickets details
    if result.failed_count > 0:
        failed = [r for r in result.ticket_results if not r.success]
        failed_text = "*Failed tickets:*\n"
        for r in failed[:5]:  # Limit to 5
            failed_text += f":x: {r.jira_key}: {r.error or 'Unknown error'}\n"
        if len(failed) > 5:
            failed_text += f"...and {len(failed) - 5} more\n"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": failed_text}
        })

        # Retry button
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Retry failed"},
                    "action_id": "decision_change_retry",
                    "value": json.dumps({"op_id": op.id}),
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "View details"},
                    "action_id": "decision_change_details",
                    "value": json.dumps({"op_id": op.id}),
                },
            ]
        })

    # Error message if overall failure
    if result.error and not result.failed_count:
        blocks.append({
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_Error: {result.error}_"}]
        })

    return blocks
