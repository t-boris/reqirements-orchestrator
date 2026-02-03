"""Inspect block builders for intent classification debugging.

Builds Slack Block Kit messages for /maro inspect command output.
All blocks follow Slack mrkdwn formatting: *bold*, _italic_, `code`.
"""

from typing import Any

from src.infrastructure.audit_log import IntentAuditEntry


def build_thread_inspect_blocks(
    entries: list[IntentAuditEntry],
) -> list[dict[str, Any]]:
    """Build blocks showing classification chain for a thread.

    Shows each message's classification details, most recent first, max 10.
    """
    blocks: list[dict[str, Any]] = []

    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"Intent Audit: {len(entries)} classifications",
        },
    })

    # Show entries most recent first, max 10
    for entry in entries[:10]:
        # Message text truncated to 100 chars
        msg_text = entry.message_text[:100]
        if len(entry.message_text) > 100:
            msg_text += "..."

        # Build classification line
        raw = entry.raw_mode or "none"
        raw_conf = f"{entry.raw_confidence:.0%}" if entry.raw_confidence is not None else "n/a"
        final = entry.classified_mode
        final_conf = f"{entry.classified_confidence:.0%}"

        classification_text = (
            f"*Message:* {msg_text}\n"
            f"`{raw}` ({raw_conf}) -> `{final}` ({final_conf})"
        )

        # Add PreGate result if not PASS_THROUGH
        if entry.pregate_result and entry.pregate_result != "PASS_THROUGH":
            classification_text += f"\n_PreGate: {entry.pregate_result}_"

        # Add reasoning if available
        if entry.reasoning:
            reasoning_truncated = entry.reasoning[:150]
            if len(entry.reasoning) > 150:
                reasoning_truncated += "..."
            classification_text += f"\n_Reasoning: {reasoning_truncated}_"

        # Add classification time
        if entry.classification_ms is not None:
            classification_text += f"\n`{entry.classification_ms}ms`"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": classification_text},
        })

        # Metadata context
        context_parts = []
        if entry.user_id:
            context_parts.append(f"<@{entry.user_id}>")
        if entry.message_ts:
            context_parts.append(f"ts: `{entry.message_ts}`")
        if entry.thread_ts:
            context_parts.append(f"thread: `{entry.thread_ts}`")

        if context_parts:
            blocks.append({
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": " | ".join(context_parts)},
                ],
            })

    if len(entries) > 10:
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"_...and {len(entries) - 10} more entries_"},
            ],
        })

    return blocks


def build_stats_inspect_blocks(
    entries: list[IntentAuditEntry],
) -> list[dict[str, Any]]:
    """Build blocks showing classification distribution stats.

    Shows mode distribution with counts and avg confidence,
    plus overall average classification time and downgrade count.
    """
    blocks: list[dict[str, Any]] = []

    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"Classification Stats (last {len(entries)} messages)",
        },
    })

    # Mode distribution: count and avg confidence per mode
    mode_stats: dict[str, dict[str, float]] = {}
    total_ms = 0
    ms_count = 0
    downgrade_count = 0

    for entry in entries:
        mode = entry.classified_mode
        if mode not in mode_stats:
            mode_stats[mode] = {"count": 0, "total_conf": 0.0}
        mode_stats[mode]["count"] += 1
        mode_stats[mode]["total_conf"] += entry.classified_confidence

        if entry.classification_ms is not None:
            total_ms += entry.classification_ms
            ms_count += 1

        if entry.raw_mode and entry.raw_mode != entry.classified_mode:
            downgrade_count += 1

    # Build distribution text
    dist_lines = ["*Mode Distribution:*\n"]
    for mode, stats in sorted(mode_stats.items(), key=lambda x: x[1]["count"], reverse=True):
        count = int(stats["count"])
        avg_conf = stats["total_conf"] / count if count > 0 else 0
        pct = count / len(entries) * 100
        dist_lines.append(f"  `{mode}`: {count} ({pct:.0f}%) | avg confidence: {avg_conf:.0%}")

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(dist_lines)},
    })

    # Avg classification time
    summary_parts = []
    if ms_count > 0:
        avg_ms = total_ms / ms_count
        summary_parts.append(f"*Avg classification time:* `{avg_ms:.0f}ms`")

    summary_parts.append(f"*Downgrades:* {downgrade_count} (raw_mode != classified_mode)")

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(summary_parts)},
    })

    return blocks


def build_downgrades_inspect_blocks(
    entries: list[IntentAuditEntry],
) -> list[dict[str, Any]]:
    """Build blocks showing threshold downgrades.

    Shows entries where raw_mode != classified_mode, max 15.
    """
    blocks: list[dict[str, Any]] = []

    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": f"Threshold Downgrades ({len(entries)})",
        },
    })

    for entry in entries[:15]:
        raw = entry.raw_mode or "none"
        raw_conf = f"{entry.raw_confidence:.0%}" if entry.raw_confidence is not None else "n/a"
        final = entry.classified_mode

        downgrade_text = f"`{raw}` ({raw_conf}) -> `{final}`"

        if entry.reasoning:
            reasoning_truncated = entry.reasoning[:150]
            if len(entry.reasoning) > 150:
                reasoning_truncated += "..."
            downgrade_text += f"\n_Reasoning: {reasoning_truncated}_"

        # Truncated message text for context
        msg_text = entry.message_text[:80]
        if len(entry.message_text) > 80:
            msg_text += "..."
        downgrade_text += f"\n_{msg_text}_"

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": downgrade_text},
        })

    if len(entries) > 15:
        blocks.append({
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"_...and {len(entries) - 15} more downgrades_"},
            ],
        })

    return blocks
