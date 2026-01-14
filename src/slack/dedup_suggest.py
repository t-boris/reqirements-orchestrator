"""Deduplication suggestions for similar threads.

Rule 2: Traffic Cop - Non-blocking suggestions only.
"""

import logging
from typing import Optional
from slack_sdk.web import WebClient

from src.memory.zep_client import search_similar_threads
from src.slack.session import SessionIdentity

logger = logging.getLogger(__name__)

# High threshold to avoid false positives
SIMILARITY_THRESHOLD = 0.85


async def check_for_duplicates(
    message_text: str,
    identity: SessionIdentity,
    epic_key: Optional[str] = None,
) -> Optional[dict]:
    """Check if similar thread exists.

    Returns similar thread info if found with high confidence.
    Returns None if no similar thread or below threshold.

    Args:
        message_text: Message content to check
        identity: Current session identity
        epic_key: Optionally filter to same Epic

    Returns:
        {session_id, summary, score, thread_link} or None
    """
    try:
        similar = await search_similar_threads(
            query=message_text,
            epic_key=epic_key,
            limit=1,
        )

        if not similar:
            return None

        top_match = similar[0]
        score = top_match.get("score", 0)

        # Only suggest if extremely high confidence
        if score < SIMILARITY_THRESHOLD:
            logger.debug(
                f"Similar thread below threshold",
                extra={
                    "score": score,
                    "threshold": SIMILARITY_THRESHOLD,
                }
            )
            return None

        # Parse session_id to get thread link
        # Format: team:channel:thread_ts
        parts = top_match["session_id"].split(":")
        if len(parts) >= 3:
            channel_id = parts[1]
            thread_ts = parts[2]
            thread_link = f"slack://channel?team={parts[0]}&id={channel_id}&message={thread_ts}"
        else:
            thread_link = None

        logger.info(
            f"Similar thread found",
            extra={
                "current_session": identity.session_id,
                "similar_session": top_match["session_id"],
                "score": score,
                "rationale": "Semantic similarity above threshold",
            }
        )

        return {
            "session_id": top_match["session_id"],
            "summary": top_match.get("summary", ""),
            "score": score,
            "thread_link": thread_link,
        }

    except Exception as e:
        logger.warning(f"Dedup check failed: {e}")
        return None


def build_dedup_suggestion_blocks(
    similar_thread: dict,
    current_summary: str,
) -> list[dict]:
    """Build blocks for dedup suggestion message.

    Non-blocking: Just a suggestion with optional action.
    """
    blocks = []

    # Info section
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f":information_source: *Similar discussion found*\n\n"
                    f"_{similar_thread['summary'][:200]}..._\n\n"
                    f"Similarity: {similar_thread['score']:.0%}"
        }
    })

    # Action buttons
    actions = []

    if similar_thread.get("thread_link"):
        actions.append({
            "type": "button",
            "text": {
                "type": "plain_text",
                "text": "View related thread",
                "emoji": True
            },
            "url": similar_thread["thread_link"],
            "action_id": "view_similar_thread",
        })

    actions.append({
        "type": "button",
        "text": {
            "type": "plain_text",
            "text": "Merge context",
            "emoji": True
        },
        "value": similar_thread["session_id"],
        "action_id": "merge_thread_context",
    })

    actions.append({
        "type": "button",
        "text": {
            "type": "plain_text",
            "text": "Ignore",
            "emoji": True
        },
        "action_id": "ignore_dedup_suggestion",
    })

    blocks.append({
        "type": "actions",
        "elements": actions
    })

    # Context note
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": "This is just a suggestion - continue your discussion normally."
        }]
    })

    return blocks


async def maybe_suggest_dedup(
    client: WebClient,
    identity: SessionIdentity,
    message_text: str,
    epic_key: Optional[str] = None,
) -> bool:
    """Check for duplicates and post suggestion if found.

    Returns True if suggestion was posted, False otherwise.
    """
    similar = await check_for_duplicates(
        message_text=message_text,
        identity=identity,
        epic_key=epic_key,
    )

    if not similar:
        return False

    blocks = build_dedup_suggestion_blocks(
        similar_thread=similar,
        current_summary=message_text[:200],
    )

    client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        text="Similar discussion found",
        blocks=blocks,
    )

    return True
