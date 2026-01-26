"""Conflict detection for draft field updates.

Detects semantic contradictions between different users' contributions
using LLM-based contradiction checking.
"""
import json
import logging
from typing import Optional

from src.schemas.attribution import MessageAttribution
from src.schemas.conflict import DraftConflict, ConflictType, ConflictSide
from src.llm import get_llm

logger = logging.getLogger(__name__)


CONTRADICTION_CHECK_PROMPT = '''Check if these two statements contradict each other.

Statement A (existing):
{existing}

Statement B (proposed):
{proposed}

Return JSON:
{{"contradicts": true/false, "explanation": "brief explanation"}}

Only return true if they are truly incompatible - they can't both be true at the same time.
Return false if they:
- Are about different things
- One adds detail to the other
- They describe different aspects
- One is a refinement of the other

JSON response:'''


async def detect_value_conflict(
    field_name: str,
    existing_value: str,
    proposed_value: str,
    existing_attribution: MessageAttribution,
    proposed_attribution: MessageAttribution,
) -> Optional[DraftConflict]:
    """Detect if a proposed value conflicts with existing.

    Uses LLM to check semantic contradiction between values.
    Returns DraftConflict if contradiction detected, None otherwise.

    Args:
        field_name: Field being updated
        existing_value: Current value in draft
        proposed_value: New value being proposed
        existing_attribution: Who set the existing value
        proposed_attribution: Who is proposing the new value

    Returns:
        DraftConflict if contradiction found, None if compatible
    """
    # Don't flag conflict if same user is updating
    if existing_attribution.author_user_id == proposed_attribution.author_user_id:
        return None

    # Don't flag conflict for empty existing values
    if not existing_value or not existing_value.strip():
        return None

    # Check if values are semantically the same or compatible
    try:
        llm = get_llm()
        prompt = CONTRADICTION_CHECK_PROMPT.format(
            existing=existing_value,
            proposed=proposed_value,
        )
        response_text = await llm.chat(prompt)
        response_text = response_text.strip()

        # Parse JSON response
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        result = json.loads(response_text) if response_text else {}

        if not result.get("contradicts", False):
            logger.debug(
                f"No conflict detected for {field_name}",
                extra={"explanation": result.get("explanation", "")},
            )
            return None

        # Create conflict
        conflict = DraftConflict(
            conflict_type=ConflictType.VALUE_OVERRIDE,
            field_name=field_name,
            description=result.get("explanation", f"Conflicting values for {field_name}"),
            existing=ConflictSide(
                content=existing_value,
                attribution=existing_attribution,
                label="Keep original",
            ),
            proposed=ConflictSide(
                content=proposed_value,
                attribution=proposed_attribution,
                label="Use new",
            ),
        )

        logger.info(
            f"Conflict detected for {field_name}",
            extra={
                "conflict_id": conflict.conflict_id,
                "existing_author": existing_attribution.author_user_id,
                "proposed_author": proposed_attribution.author_user_id,
            },
        )

        return conflict

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse contradiction check response: {e}")
        return None
    except Exception as e:
        logger.warning(f"Contradiction check failed: {e}")
        return None


async def store_and_signal_conflicts(
    channel_id: str,
    thread_ts: str,
    conflicts: list[DraftConflict],
) -> None:
    """Store detected conflicts in database.

    Called when extraction detects semantic conflicts between
    different users' contributions. Stores conflicts for
    later resolution via UI buttons.

    Args:
        channel_id: Slack channel ID
        thread_ts: Thread timestamp
        conflicts: List of DraftConflict objects to store
    """
    from src.db import get_connection
    from src.db.conflict_store import ConflictStore

    try:
        async with get_connection() as conn:
            store = ConflictStore(conn)
            await store.ensure_table()
            for conflict in conflicts:
                await store.create(channel_id, thread_ts, conflict)
                logger.info(
                    f"Stored conflict: {conflict.conflict_id}",
                    extra={
                        "field": conflict.field_name,
                        "type": conflict.conflict_type.value,
                    },
                )
    except Exception as e:
        logger.error(f"Failed to store conflicts: {e}")
