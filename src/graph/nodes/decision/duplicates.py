"""Duplicate detection for decision node.

Channel-first duplicate detection - checks local truth before remote.
This reflects the Git model: check local (channel) before remote (Jira).
"""
import logging
from typing import Optional

from src.schemas.draft import TicketDraft

logger = logging.getLogger(__name__)


async def _explain_duplicate_match(
    draft: TicketDraft,
    duplicate: dict,
) -> str:
    """Generate concise explanation of why duplicate matches draft.

    Uses LLM to identify matching aspects: feature area, action, entities.

    Returns:
        Explanation like "same feature area (notifications), same main action (scheduling)"
        or empty string on error.
    """
    try:
        from src.llm import get_llm

        llm = get_llm()

        prompt = f"""Compare these two ticket descriptions and explain why they might be related in ONE SHORT phrase (max 80 chars).

Draft ticket title: "{draft.title}"
Draft problem: "{draft.problem[:200] if draft.problem else 'Not specified'}"

Existing ticket: "{duplicate.get('summary', '')}"

Focus on what they have in common:
- Same feature area? (e.g., "same feature area (notifications)")
- Same action type? (e.g., "same action (scheduling)")
- Same entities? (e.g., "same entities (user accounts)")

Respond with ONLY a short phrase explaining the match. Examples:
- "same feature area (notifications), same action (scheduling)"
- "both about user authentication"
- "related to payment processing"

If they don't seem related, respond with empty string."""

        result = await llm.chat(prompt)

        # Clean and validate response (llm.chat returns str directly)
        explanation = result.strip().strip('"').strip()

        # Truncate if too long
        if len(explanation) > 100:
            explanation = explanation[:97] + "..."

        # Reject if it looks like refusal or error
        if any(word in explanation.lower() for word in ["sorry", "cannot", "don't", "i am", "i'm"]):
            return ""

        return explanation

    except Exception as e:
        logger.warning(f"Failed to generate match explanation: {e}")
        return ""


def _compute_confidence_score(draft: TicketDraft, duplicate: dict) -> float:
    """Compute confidence score for a duplicate match.

    Uses multiple signals to determine confidence:
    - Title similarity (word overlap)
    - Problem description similarity
    - Same status (lower confidence if already done)

    Args:
        draft: The draft ticket being created.
        duplicate: Dict with key, summary, status, etc.

    Returns:
        Confidence score from 0.0 to 1.0.
    """
    score = 0.0

    # Normalize strings for comparison
    draft_title = (draft.title or "").lower().strip()
    draft_problem = (draft.problem or "").lower().strip()
    dup_summary = (duplicate.get("summary") or "").lower().strip()

    if not draft_title or not dup_summary:
        return 0.0

    # Title word overlap (up to 0.5)
    draft_words = set(draft_title.split())
    dup_words = set(dup_summary.split())

    # Remove common words
    stop_words = {"the", "a", "an", "is", "are", "to", "for", "and", "or", "as", "in", "on", "at", "with"}
    draft_words = draft_words - stop_words
    dup_words = dup_words - stop_words

    if draft_words and dup_words:
        overlap = len(draft_words & dup_words)
        max_possible = max(len(draft_words), len(dup_words))
        title_score = (overlap / max_possible) * 0.5
        score += title_score

    # Problem description overlap (up to 0.3)
    if draft_problem:
        problem_words = set(draft_problem.split()) - stop_words
        if problem_words:
            dup_all_words = dup_words | set(duplicate.get("description", "").lower().split())
            overlap = len(problem_words & dup_all_words)
            max_possible = max(len(problem_words), len(dup_all_words)) if dup_all_words else len(problem_words)
            problem_score = (overlap / max_possible) * 0.3 if max_possible > 0 else 0.0
            score += problem_score

    # Boost for active tickets (up to 0.2)
    status = (duplicate.get("status") or "").lower()
    if status in ("to do", "open", "new", "in progress", "in review"):
        score += 0.2
    elif status in ("done", "closed", "resolved"):
        # Lower confidence for already done tickets
        score += 0.05

    return min(score, 1.0)


async def _search_channel_registry(
    draft: TicketDraft,
    channel_id: str,
) -> list[dict]:
    """Search channel's WorkItem registry for duplicates.

    Channel-first duplicate detection - checks local truth before remote.
    This reflects the Git model: check local (channel) before remote (Jira).

    Args:
        draft: The draft ticket being created.
        channel_id: The channel to search in.

    Returns:
        List of matching workitems as dicts with confidence scores.
    """
    try:
        from src.db import get_connection
        from src.db.workitem_store import WorkItemStore
        from src.db.models import WorkItemStatus

        duplicates = []

        async with get_connection() as conn:
            store = WorkItemStore(conn)
            workitems = await store.list_by_channel(
                channel_id,
                status=[WorkItemStatus.DRAFT, WorkItemStatus.ACTIVE],
                limit=50,
            )

            draft_title = (draft.title or "").lower()
            draft_problem = (draft.problem or "").lower()

            for item in workitems:
                confidence = _compute_channel_similarity(
                    draft_title,
                    draft_problem,
                    (item.summary or "").lower(),
                    (item.description or "").lower(),
                )

                if confidence >= 0.5:  # Threshold for channel matches
                    duplicates.append({
                        "workitem_id": item.id,
                        "jira_key": item.jira_key,
                        "key": item.jira_key or item.id[:8],
                        "summary": item.summary,
                        "status": item.status.value,
                        "confidence": confidence,
                        "source": "channel",
                        "match_reason": "",
                    })

        # Sort by confidence
        duplicates.sort(key=lambda x: x["confidence"], reverse=True)
        return duplicates[:5]  # Top 5

    except Exception as e:
        logger.warning(f"Failed to search channel registry: {e}")
        return []


def _compute_channel_similarity(
    draft_title: str,
    draft_problem: str,
    item_summary: str,
    item_description: str,
) -> float:
    """Compute similarity score between draft and existing item.

    Used for channel-first duplicate detection.

    Args:
        draft_title: Draft title (lowercased)
        draft_problem: Draft problem statement (lowercased)
        item_summary: Existing item summary (lowercased)
        item_description: Existing item description (lowercased)

    Returns:
        Confidence score from 0.0 to 1.0.
    """
    score = 0.0

    # Remove common stop words
    stop_words = {"the", "a", "an", "is", "are", "to", "for", "and", "or", "as", "in", "on", "at", "with"}

    # Title word overlap (up to 0.5)
    draft_words = set(draft_title.split()) - stop_words
    item_words = set(item_summary.split()) - stop_words
    if draft_words and item_words:
        overlap = len(draft_words & item_words)
        max_words = max(len(draft_words), len(item_words))
        score += (overlap / max_words) * 0.5

    # Problem/description overlap (up to 0.3)
    if draft_problem and item_description:
        draft_prob_words = set(draft_problem.split()) - stop_words
        item_desc_words = set(item_description.split()) - stop_words
        if draft_prob_words and item_desc_words:
            overlap = len(draft_prob_words & item_desc_words)
            max_words = max(len(draft_prob_words), len(item_desc_words))
            score += (overlap / max_words) * 0.3

    # Boost for exact title match
    if draft_title == item_summary:
        score = min(score + 0.3, 1.0)

    return score


async def search_for_duplicates(
    draft: Optional[TicketDraft],
    channel_id: Optional[str] = None,
) -> tuple[list[dict], list[float]]:
    """Search for duplicates - channel first, then Jira.

    Order:
    1. Check channel WorkItem registry (local truth)
    2. If no high-confidence match, check Jira (remote replica)

    This reflects the Git model: check local before remote.

    Returns tuple of:
    - list of {key, summary, url, status, assignee, updated, match_reason, source} dicts
    - list of confidence scores (0.0-1.0) for each duplicate

    For the best match (first), generates LLM explanation of why it matches.
    Fails gracefully - returns empty lists on any error.
    """
    if not draft or not draft.title:
        return [], []

    duplicates = []
    confidence_scores = []
    best_confidence = 0.0

    # 1. Search channel registry first (local)
    if channel_id:
        try:
            channel_duplicates = await _search_channel_registry(draft, channel_id)
            for dup in channel_duplicates:
                dup["source"] = "channel"  # Mark as local match
                duplicates.append(dup)
                conf = dup.get("confidence", 0)
                confidence_scores.append(conf)
                if conf > best_confidence:
                    best_confidence = conf

            if channel_duplicates:
                logger.info(
                    "Found channel registry matches",
                    extra={
                        "count": len(channel_duplicates),
                        "best_confidence": best_confidence,
                        "channel_id": channel_id,
                    },
                )
        except Exception as e:
            logger.warning(f"Channel registry search failed: {e}")

    # 2. If high confidence local match, skip Jira search
    if best_confidence >= 0.85:
        # Generate match explanation for best match
        if duplicates:
            match_reason = await _explain_duplicate_match(draft, duplicates[0])
            duplicates[0]["match_reason"] = match_reason
        return duplicates, confidence_scores

    # 3. Search Jira (remote)
    try:
        from src.config.settings import get_settings
        from src.jira.client import JiraService
        from src.skills.jira_search import search_similar_to_draft

        settings = get_settings()
        jira_service = JiraService(settings)

        try:
            result = await search_similar_to_draft(draft, jira_service, limit=5)

            # Track existing jira_keys from channel matches
            existing_keys = {d.get("jira_key") for d in duplicates if d.get("jira_key")}

            for issue in result.issues[:5]:
                # Skip if already in channel registry (avoid duplicates)
                if issue.key in existing_keys:
                    continue

                dup = {
                    "key": issue.key,
                    "summary": issue.summary,
                    "url": issue.url,
                    "status": issue.status,
                    "assignee": issue.assignee,
                    "updated": issue.updated,
                    "match_reason": "",
                    "source": "jira",  # Mark as remote match
                }

                # Compute confidence score
                confidence = _compute_confidence_score(draft, dup)
                duplicates.append(dup)
                confidence_scores.append(confidence)

        finally:
            await jira_service.close()

    except Exception as e:
        # Don't fail the workflow if Jira search fails
        logger.warning(
            "Failed to search Jira for duplicates",
            extra={"error": str(e)},
        )

    # Sort all results by confidence descending
    if duplicates:
        pairs = sorted(
            zip(duplicates, confidence_scores),
            key=lambda x: x[1],
            reverse=True
        )
        duplicates = [p[0] for p in pairs]
        confidence_scores = [p[1] for p in pairs]

        # Generate match explanation for best match only
        match_reason = await _explain_duplicate_match(draft, duplicates[0])
        duplicates[0]["match_reason"] = match_reason

        logger.info(
            "Found potential duplicates (channel-first)",
            extra={
                "count": len(duplicates),
                "draft_title": draft.title[:50],
                "best_match": duplicates[0].get("key"),
                "best_source": duplicates[0].get("source"),
                "best_confidence": confidence_scores[0] if confidence_scores else 0.0,
                "match_reason": match_reason,
            },
        )

    return duplicates, confidence_scores
