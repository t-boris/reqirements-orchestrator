"""Jira helper functions - shared utilities.

Contains formatting and parsing helpers used across Jira modules.
"""
from datetime import datetime, timezone


def format_updated_time(iso_timestamp: str) -> str:
    """Format Jira updated timestamp to relative time string.

    Args:
        iso_timestamp: ISO 8601 timestamp from Jira (e.g., "2026-01-15T10:30:00.000+0000")

    Returns:
        Human-readable relative time (e.g., "3 days ago", "2 hours ago")
    """
    try:
        # Parse ISO timestamp - Jira uses format like "2026-01-15T10:30:00.000+0000"
        # Remove milliseconds and normalize timezone
        ts = iso_timestamp.replace("+0000", "+00:00").replace("Z", "+00:00")
        if "." in ts:
            # Remove milliseconds
            ts = ts.split(".")[0] + ts[-6:] if "+" in ts else ts.split(".")[0]

        updated_dt = datetime.fromisoformat(ts.replace("+00:00", "")).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - updated_dt

        if delta.days > 30:
            months = delta.days // 30
            return f"{months} month{'s' if months > 1 else ''} ago"
        elif delta.days > 0:
            return f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
        elif delta.seconds >= 3600:
            hours = delta.seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif delta.seconds >= 60:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        else:
            return "just now"
    except Exception:
        # Return raw timestamp if parsing fails
        return iso_timestamp[:10] if len(iso_timestamp) > 10 else iso_timestamp
