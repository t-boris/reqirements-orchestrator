"""Mention formatting utilities for multi-user support.

Handles:
- Formatting user mentions in Slack messages
- Reply prefix logic (direct question → @user, general → "Team,")
- Mention limiting to prevent spam (max 2 @mentions per message)
- Direct question detection

Phase 27.2 - Participant Map & Turn-Taking
"""
import re
from typing import Optional


MAX_MENTIONS_PER_MESSAGE = 2


def format_user_mention(user_id: str) -> str:
    """Format a Slack user mention.

    Args:
        user_id: Slack user ID (e.g., "U01ABC123")

    Returns:
        Slack mention format (e.g., "<@U01ABC123>")
    """
    return f"<@{user_id}>"


def format_reply_prefix(
    direct_to_user_id: Optional[str] = None,
    is_general: bool = False,
) -> str:
    """Format reply prefix based on context.

    Args:
        direct_to_user_id: If set, address this specific user
        is_general: If True, use neutral "Team," prefix

    Returns:
        Reply prefix string (with trailing space if not empty)

    Examples:
        >>> format_reply_prefix(direct_to_user_id="U01ABC")
        '<@U01ABC>, '
        >>> format_reply_prefix(is_general=True)
        'Team, '
        >>> format_reply_prefix()
        ''
    """
    if direct_to_user_id:
        return f"<@{direct_to_user_id}>, "
    if is_general:
        return "Team, "
    return ""


def limit_mentions(text: str, max_mentions: int = MAX_MENTIONS_PER_MESSAGE) -> str:
    """Limit @mentions in text to prevent spam.

    Replaces excess mentions with non-pinging "@user" placeholder.

    Args:
        text: Message text potentially containing mentions
        max_mentions: Maximum number of mentions to preserve

    Returns:
        Text with excess mentions converted to non-pinging format

    Examples:
        >>> limit_mentions("<@U1> <@U2> <@U3>", max_mentions=2)
        '<@U1> <@U2> @user'
    """
    mention_pattern = r"<@([A-Z0-9]+)>"
    mentions = re.findall(mention_pattern, text)

    if len(mentions) <= max_mentions:
        return text

    # Keep first N mentions, convert rest to non-pinging format
    mention_count = 0

    def replace_excess(match):
        nonlocal mention_count
        mention_count += 1
        if mention_count <= max_mentions:
            return match.group(0)  # Keep original
        return "@user"  # Non-pinging placeholder

    return re.sub(mention_pattern, replace_excess, text)


def detect_direct_question(
    text: str,
    participant_user_ids: list[str],
    bot_user_id: Optional[str] = None,
) -> Optional[str]:
    """Detect if message is a direct question to a specific user.

    Checks if the message starts with an @mention to a known participant.
    Returns the user_id if it's a direct question to them.

    Args:
        text: Message text to analyze
        participant_user_ids: List of user IDs who are thread participants
        bot_user_id: Optional bot user ID to exclude from detection

    Returns:
        user_id if direct question detected, None otherwise

    Examples:
        >>> detect_direct_question("<@U01ABC> what do you think?", ["U01ABC", "U02DEF"])
        'U01ABC'
        >>> detect_direct_question("general question here", ["U01ABC"])
        None
    """
    # Check for @mention at start of message (after stripping whitespace)
    match = re.match(r"^<@([A-Z0-9]+)>", text.strip())
    if not match:
        return None

    mentioned_user = match.group(1)

    # Exclude bot mentions - those are commands to the bot, not questions to users
    if bot_user_id and mentioned_user == bot_user_id:
        return None

    # Only return if mentioned user is a known participant
    if mentioned_user in participant_user_ids:
        return mentioned_user

    return None


def extract_mentions(text: str) -> list[str]:
    """Extract all user IDs mentioned in text.

    Args:
        text: Message text to analyze

    Returns:
        List of user IDs mentioned (without duplicates, preserving order)

    Examples:
        >>> extract_mentions("<@U01ABC> and <@U02DEF> discussed <@U01ABC>")
        ['U01ABC', 'U02DEF']
    """
    mention_pattern = r"<@([A-Z0-9]+)>"
    mentions = re.findall(mention_pattern, text)
    # Remove duplicates while preserving order
    seen = set()
    unique = []
    for m in mentions:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    return unique


def count_mentions(text: str) -> int:
    """Count unique mentions in text.

    Args:
        text: Message text to analyze

    Returns:
        Number of unique user mentions
    """
    return len(extract_mentions(text))


def is_over_mention_limit(text: str, max_mentions: int = MAX_MENTIONS_PER_MESSAGE) -> bool:
    """Check if text exceeds mention limit.

    Args:
        text: Message text to check
        max_mentions: Maximum allowed mentions

    Returns:
        True if mention count exceeds limit
    """
    return count_mentions(text) > max_mentions
