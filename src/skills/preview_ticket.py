"""preview_ticket skill - shows draft preview with approval buttons.

Posts ticket draft preview to Slack with:
- All draft fields formatted
- Evidence permalinks inline
- Approval buttons with embedded version hash
- Version checking to ensure user approves exactly what they see
"""
import hashlib
import logging
from typing import Optional
from pydantic import BaseModel, Field

from slack_sdk.web.async_client import AsyncWebClient

from src.schemas.draft import TicketDraft

logger = logging.getLogger(__name__)


class PreviewResult(BaseModel):
    """Result of posting a draft preview."""

    message_ts: str = Field(description="Slack message timestamp of preview")
    preview_id: str = Field(description="Unique ID for this preview")
    draft_hash: str = Field(description="Hash of draft content for version checking")
    status: str = Field(default="posted", description="Status of the preview")


def compute_draft_hash(draft: TicketDraft) -> str:
    """Compute deterministic hash of draft content.

    Hash is based on core fields that define the ticket:
    - title
    - problem
    - acceptance_criteria

    Returns:
        8-character hex hash
    """
    # Build deterministic string from core content
    ac_str = ",".join(sorted(draft.acceptance_criteria)) if draft.acceptance_criteria else ""
    content = f"{draft.title or ''}|{draft.problem or ''}|{ac_str}"

    # SHA256 truncated to 8 chars
    full_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return full_hash[:8]


async def preview_ticket(
    client: AsyncWebClient,
    channel: str,
    thread_ts: str,
    draft: TicketDraft,
    session_id: str,
    evidence_permalinks: Optional[list[dict]] = None,
    potential_duplicates: Optional[list[dict]] = None,
) -> PreviewResult:
    """Post draft preview with approval buttons.

    Args:
        client: Slack async web client
        channel: Channel ID to post in
        thread_ts: Thread timestamp to post in
        draft: Ticket draft to preview
        session_id: Session ID for button values
        evidence_permalinks: Optional list of {permalink, user, preview} for evidence
        potential_duplicates: Optional list of {key, summary, url} for duplicate display

    Returns:
        PreviewResult with message_ts, preview_id, draft_hash, status
    """
    # Compute hash for version checking
    draft_hash = compute_draft_hash(draft)

    logger.info(
        f"preview_ticket called with {len(potential_duplicates) if potential_duplicates else 0} duplicates"
    )

    # Import blocks builder
    from src.slack.blocks import build_draft_preview_blocks_with_hash

    # Build blocks with hash embedded in button values
    blocks = build_draft_preview_blocks_with_hash(
        draft=draft,
        session_id=session_id,
        draft_hash=draft_hash,
        evidence_permalinks=evidence_permalinks,
        potential_duplicates=potential_duplicates,
    )

    # Post preview (WebClient is sync, not async)
    response = client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts,
        text=f"Here's the ticket preview for: {draft.title or 'Untitled'}",
        blocks=blocks,
    )

    message_ts = response["ts"]

    logger.info(
        "Posted draft preview",
        extra={
            "channel": channel,
            "thread_ts": thread_ts,
            "message_ts": message_ts,
            "draft_hash": draft_hash,
            "session_id": session_id,
        },
    )

    return PreviewResult(
        message_ts=message_ts,
        preview_id=f"{session_id}:{draft_hash}",
        draft_hash=draft_hash,
        status="posted",
    )
