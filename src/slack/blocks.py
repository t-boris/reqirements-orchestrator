"""Slack Block Kit builders for rich messages."""

from typing import Any, Optional


def get_draft_state_badge(state: str) -> str:
    """Return emoji badge for draft state.

    Args:
        state: Draft lifecycle state (draft, approved, created, linked)

    Returns:
        Formatted badge string with emoji and state name
    """
    badges = {
        "draft": "🟡 Draft",
        "approved": "🟢 Approved",
        "created": "✅ Created",
        "linked": "🔗 Linked",
    }
    return badges.get(state, "🟡 Draft")


def build_session_card(
    epic_key: Optional[str],
    epic_summary: Optional[str],
    session_status: str,
    thread_ts: str,
) -> list[dict]:
    """Build Session Card blocks for thread header.

    Shows: Epic link, session status, available commands.
    """
    blocks = []

    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "Session Active",
            "emoji": True
        }
    })

    # Epic info section
    if epic_key:
        epic_text = f"*Epic:* <https://jira.example.com/browse/{epic_key}|{epic_key}>"
        if epic_summary:
            epic_text += f" - {epic_summary}"
    else:
        epic_text = "*Epic:* _Not linked yet_"

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": epic_text
        }
    })

    # Status
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Status:* {session_status}"
        }
    })

    # Commands
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": "Commands: `/jira status` | `/jira create` | @mention me"
        }]
    })

    return blocks


def build_epic_selector(
    suggested_epics: list[dict],
    message_preview: str,
) -> list[dict]:
    """Build Epic selection blocks.

    Args:
        suggested_epics: List of {key, summary, score} dicts
        message_preview: First part of user's message for context
    """
    blocks = []

    # Context
    preview_text = message_preview[:100]
    if len(message_preview) > 100:
        preview_text += "..."

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"I see you're discussing: _{preview_text}_\n\nWhich Epic does this relate to?"
        }
    })

    # Suggested epics as buttons
    if suggested_epics:
        buttons = []
        for epic in suggested_epics[:3]:  # Max 3 suggestions
            # Truncate summary for button text (max 75 chars total)
            button_text = f"{epic['key']}: {epic['summary'][:30]}"
            if len(epic['summary']) > 30:
                button_text += "..."

            buttons.append({
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": button_text[:75],  # Slack limit
                    "emoji": True
                },
                "value": epic["key"],
                "action_id": f"select_epic_{epic['key']}"
            })

        # Add "New Epic" option
        buttons.append({
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "New Epic",
                "emoji": True
            },
            "value": "new",
            "action_id": "select_epic_new",
            "style": "primary"
        })

        blocks.append({
            "type": "actions",
            "elements": buttons
        })
    else:
        # No suggestions, just show "New Epic"
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "Create New Epic",
                    "emoji": True
                },
                "value": "new",
                "action_id": "select_epic_new",
                "style": "primary"
            }]
        })

    return blocks


def build_draft_preview_blocks(draft: "TicketDraft") -> list[dict]:
    """Build Slack blocks for ticket draft preview (legacy).

    Shows all draft fields with approval buttons.
    Note: Use build_draft_preview_blocks_with_hash for version-checked previews.
    """
    # Use new function with None hash (legacy behavior)
    return build_draft_preview_blocks_with_hash(
        draft=draft,
        session_id=draft.id,
        draft_hash="",
        evidence_permalinks=None,
        potential_duplicates=None,
    )


def build_draft_preview_blocks_with_hash(
    draft: "TicketDraft",
    session_id: str,
    draft_hash: str,
    evidence_permalinks: Optional[list[dict]] = None,
    potential_duplicates: Optional[list[dict]] = None,
    validator_findings: Optional[dict[str, Any]] = None,
    draft_state: str = "draft",
) -> list[dict]:
    """Build Slack blocks for ticket draft preview with version hash.

    Embeds draft_hash in button values for version checking.
    Shows evidence links inline with permalinks.
    Shows potential duplicates before approval buttons if found.
    Shows validator findings with hybrid UX (Phase 9).

    Args:
        draft: TicketDraft to display
        session_id: Session ID for button value prefix
        draft_hash: Hash of draft content for version checking
        evidence_permalinks: Optional list of {permalink, user, preview} dicts
        potential_duplicates: Optional list of {key, summary, url} dicts for duplicate display
        validator_findings: Optional ValidationFindings dict with findings
        draft_state: Lifecycle state of draft (draft, approved, created, linked)
    """
    from src.schemas.draft import TicketDraft

    blocks = []

    # Check for blocking findings
    has_blocking = validator_findings and validator_findings.get("has_blocking", False)

    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": ":ticket: Draft Preview" if not has_blocking else ":warning: Draft Preview - Issues Found",
            "emoji": True
        }
    })

    # State badge (Phase 11.2)
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": get_draft_state_badge(draft_state)
        }]
    })

    # If blocking findings, show them first (prominently)
    if has_blocking:
        findings_blocks = build_findings_blocks(validator_findings, max_inline=2, max_review=3)
        blocks.extend(findings_blocks)
        blocks.append({"type": "divider"})

    # Title
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Title:* {draft.title or '_Not set_'}"
        }
    })

    # Problem
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"*Problem:*\n{draft.problem or '_Not set_'}"
        }
    })

    # Solution (if present)
    if draft.proposed_solution:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Proposed Solution:*\n{draft.proposed_solution}"
            }
        })

    # Acceptance Criteria
    if draft.acceptance_criteria:
        ac_text = "*Acceptance Criteria:*\n"
        for i, ac in enumerate(draft.acceptance_criteria, 1):
            ac_text += f"{i}. {ac}\n"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ac_text
            }
        })

    # Constraints (if present)
    if draft.constraints:
        constraints_text = "*Constraints:*\n"
        for c in draft.constraints:
            constraints_text += f"• `{c.key}` = `{c.value}` ({c.status.value})\n"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": constraints_text
            }
        })

    # Evidence sources (if provided)
    if evidence_permalinks:
        sources_text = "*Sources:*\n"
        for evidence in evidence_permalinks[:3]:  # Max 3 sources
            permalink = evidence.get("permalink", "#")
            user = evidence.get("user", "user")
            preview = evidence.get("preview", "")[:50]
            if len(evidence.get("preview", "")) > 50:
                preview += "..."
            sources_text += f"• <{permalink}|Message from @{user}>: \"{preview}\"\n"
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": sources_text
            }
        })

    # Non-blocking findings at bottom (Review Notes) - only if no blocking findings shown
    if validator_findings and not has_blocking:
        findings_blocks = build_findings_blocks(validator_findings, max_inline=0, max_review=5)
        if findings_blocks:
            blocks.extend(findings_blocks)

    # Build button value with session_id:draft_hash for version checking
    button_value = f"{session_id}:{draft_hash}" if draft_hash else session_id

    # When duplicates found, show duplicate blocks with action buttons (Phase 11.1)
    # This replaces the standard approval buttons
    if potential_duplicates:
        blocks.append({"type": "divider"})
        duplicate_blocks = build_duplicate_blocks(
            potential_duplicates=potential_duplicates,
            session_id=session_id,
            draft_hash=draft_hash,
        )
        blocks.extend(duplicate_blocks)
    elif has_blocking:
        # Blocking findings: "Resolve Issues" instead of "Approve"
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Resolve Issues",
                        "emoji": True
                    },
                    "value": button_value,
                    "action_id": "resolve_issues",
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Edit Draft",
                        "emoji": True
                    },
                    "value": button_value,
                    "action_id": "reject_draft",
                },
            ]
        })
    else:
        # No blocking and no duplicates: standard approval flow
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Approve & Create",
                        "emoji": True
                    },
                    "value": button_value,
                    "action_id": "approve_draft",
                    "style": "primary",
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Needs Changes",
                        "emoji": True
                    },
                    "value": button_value,
                    "action_id": "reject_draft",
                },
            ]
        })

    # Context with evidence count
    evidence_count = len(draft.evidence_links) if draft.evidence_links else 0
    context_text = f"Draft version {draft.version}"
    if evidence_count > 0:
        context_text += f" | Based on {evidence_count} messages"

    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": context_text
        }]
    })

    return blocks


def build_findings_blocks(
    findings: dict[str, Any],
    max_inline: int = 2,
    max_review: int = 5,
) -> list[dict]:
    """Build Slack blocks for validator findings.

    Hybrid approach:
    1. Inline BLOCK findings (max 2) at top
    2. "Review Notes" section for WARN/INFO at bottom
    3. "+N more" if truncated

    Args:
        findings: ValidationFindings.model_dump() dict.
        max_inline: Max BLOCK findings to show inline.
        max_review: Max WARN/INFO findings in review section.

    Returns:
        List of Slack block dicts.
    """
    if not findings or not findings.get("findings"):
        return []

    blocks = []
    all_findings = findings.get("findings", [])

    # Separate by severity
    blocking = [f for f in all_findings if f.get("severity") == "block"]
    warnings = [f for f in all_findings if f.get("severity") == "warn"]
    info = [f for f in all_findings if f.get("severity") == "info"]

    # 1. Inline BLOCK findings (critical, show prominently)
    if blocking:
        inline_blocking = blocking[:max_inline]
        for f in inline_blocking:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":warning: *BLOCK:* {f.get('message', '')}",
                },
            })
            if f.get("fix_hint"):
                blocks.append({
                    "type": "context",
                    "elements": [{
                        "type": "mrkdwn",
                        "text": f":bulb: {f.get('fix_hint')}",
                    }],
                })

        remaining_blocking = len(blocking) - max_inline
        if remaining_blocking > 0:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"+{remaining_blocking} more blocking issue(s)",
                }],
            })

    # 2. Review Notes section for WARN/INFO
    review_findings = warnings + info
    if review_findings:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Review Notes:*",
            },
        })

        # Group by persona
        by_persona: dict[str, list] = {}
        for f in review_findings[:max_review]:
            persona = f.get("persona", "pm")
            if persona not in by_persona:
                by_persona[persona] = []
            by_persona[persona].append(f)

        for persona, persona_findings in by_persona.items():
            emoji = {"pm": ":memo:", "security": ":shield:", "architect": ":building_construction:"}.get(persona, ":memo:")
            notes = []
            for f in persona_findings:
                severity_emoji = ":large_orange_diamond:" if f.get("severity") == "warn" else ":small_blue_diamond:"
                notes.append(f"{severity_emoji} {f.get('message', '')}")

            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"{emoji} *{persona.upper()}:* " + " | ".join(notes),
                }],
            })

        remaining_review = len(review_findings) - max_review
        if remaining_review > 0:
            blocks.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"+{remaining_review} more note(s) - use `/persona status` for details",
                }],
            })

    return blocks


def build_persona_indicator(
    persona: str,
    message_count: int,
    max_indicator_messages: int = 2,
) -> Optional[str]:
    """Build persona indicator prefix for messages.

    Only shows indicator on first 1-2 messages after switch.

    Args:
        persona: Current persona name.
        message_count: Messages since persona change.
        max_indicator_messages: How many messages to show indicator.

    Returns:
        Indicator prefix string or None if past threshold.
    """
    if message_count >= max_indicator_messages:
        return None

    indicators = {
        "pm": ":memo:",
        "security": ":shield:",
        "architect": ":building_construction:",
    }

    emoji = indicators.get(persona, ":memo:")
    names = {
        "pm": "PM",
        "security": "Security",
        "architect": "Architect",
    }

    return f"{emoji} *{names.get(persona, 'PM')}:*"


def build_duplicate_blocks(
    potential_duplicates: list[dict],
    session_id: str,
    draft_hash: str,
) -> list[dict]:
    """Build blocks for duplicate detection with action buttons.

    Shows rich duplicate display with match explanation and action buttons:
    - Link to this: Bind thread to existing ticket
    - Add as info: Add conversation info to existing ticket (stub)
    - Create new: Proceed with new ticket creation
    - Show more: Open modal with all matches

    Args:
        potential_duplicates: List of dicts with key, summary, url, status, assignee, updated, match_reason
        session_id: Session ID for button value encoding
        draft_hash: Hash of draft content for version checking

    Returns:
        List of Slack block dicts for duplicate display
    """
    if not potential_duplicates:
        return []

    blocks = []

    # Header
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": ":mag: *Possible existing ticket found*"
        }
    })

    # Best match (first duplicate)
    best = potential_duplicates[0]
    key = best.get("key", "Unknown")
    summary = best.get("summary", "")[:60]
    if len(best.get("summary", "")) > 60:
        summary += "..."
    url = best.get("url", "#")
    status = best.get("status", "Unknown")
    assignee = best.get("assignee", "Unassigned") or "Unassigned"
    updated = best.get("updated", "Unknown")
    match_reason = best.get("match_reason", "")

    # Main ticket info
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"I found a Jira ticket that looks very similar:\n\n"
                    f"*<{url}|{key}>* - \"{summary}\"\n"
                    f"Status: {status} | Assignee: {assignee} | Updated: {updated}"
        }
    })

    # Match reason (if available)
    if match_reason:
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f":bulb: *This matches because:* {match_reason}"
            }]
        })

    # Action buttons
    # Button value encoding: action:session_id:draft_hash:issue_key
    has_more = len(potential_duplicates) > 1

    action_buttons = [
        {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "Link to this",
                "emoji": True
            },
            "value": f"{session_id}:{draft_hash}:{key}",
            "action_id": "link_duplicate",
            "style": "primary",
        },
        {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "Add as info",
                "emoji": True
            },
            "value": f"{session_id}:{draft_hash}:{key}",
            "action_id": "add_to_duplicate",
        },
        {
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "Create new",
                "emoji": True
            },
            "value": f"{session_id}:{draft_hash}",
            "action_id": "create_anyway",
        },
    ]

    # Add "Show more" button if there are additional matches
    if has_more:
        action_buttons.append({
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": f"Show more ({len(potential_duplicates) - 1})",
                "emoji": True
            },
            "value": f"{session_id}:{draft_hash}",
            "action_id": "show_more_duplicates",
        })

    blocks.append({
        "type": "actions",
        "elements": action_buttons
    })

    return blocks


def build_linked_confirmation_blocks(
    issue_key: str,
    issue_url: str,
) -> list[dict]:
    """Build confirmation blocks after linking to existing ticket.

    Shows success message with link to the Jira ticket and option to unlink.

    Args:
        issue_key: Linked Jira issue key (e.g., PROJ-123)
        issue_url: URL to the Jira issue

    Returns:
        List of Slack block dicts for linked confirmation
    """
    blocks = []

    # Success header
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f":white_check_mark: *Linked to {issue_key}*\n\n"
                    f"This thread is now connected to the existing ticket. "
                    f"Any updates will be shared here."
        }
    })

    # View in Jira button
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {
                    "type": "plain_text",
                    "text": "View in Jira",
                    "emoji": True
                },
                "url": issue_url,
                "action_id": "view_linked_ticket",
            },
        ]
    })

    return blocks
