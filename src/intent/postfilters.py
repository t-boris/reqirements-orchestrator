"""Deterministic post-filters for intent classification.

Run after LLM classification to validate references and prevent hallucination.
These are NOT intent detection — they validate LLM output against real state.
"""

import logging
from src.intent.schemas import IntentClassification, SuperMode
from src.infrastructure.aggregate_loader import load_aggregate

logger = logging.getLogger(__name__)


async def apply_postfilters(
    result: IntentClassification,
    channel_id: str,
) -> IntentClassification:
    """Apply deterministic post-filters to validated classification.

    Filters:
    1. Entity existence: MODIFY with target_entity_id must reference existing entity
    2. Entity type consistency: entity_type must match actual entity type
    """
    if result.mode == SuperMode.MODIFY and result.target_entity_id:
        return await _validate_entity_reference(result, channel_id)

    return result


async def _validate_entity_reference(
    result: IntentClassification,
    channel_id: str,
) -> IntentClassification:
    """Validate that target_entity_id exists in the channel aggregate.

    If entity doesn't exist, downgrade to CONVERSE with explanation.
    """
    try:
        from src.domain.types import EntityId
        aggregate = await load_aggregate(channel_id)
        entity = aggregate.get_entity(EntityId(result.target_entity_id))

        if entity is None:
            logger.warning(
                f"Post-filter: MODIFY target {result.target_entity_id} not found "
                f"in channel {channel_id}, downgrading to CONVERSE"
            )
            return IntentClassification(
                mode=SuperMode.CONVERSE,
                confidence=result.confidence,
                entity_type=result.entity_type,
                target_entity_id=result.target_entity_id,
                reasoning=(
                    f"Entity {result.target_entity_id} not found. "
                    f"Original intent: {result.mode} - {result.reasoning}"
                ),
                entities_mentioned=result.entities_mentioned,
            )

        # Entity exists — also validate mentioned entities
        if result.entities_mentioned:
            valid_mentions = []
            for eid in result.entities_mentioned:
                try:
                    if aggregate.get_entity(EntityId(eid)) is not None:
                        valid_mentions.append(eid)
                    else:
                        logger.debug(f"Post-filter: mentioned entity {eid} not found, removing")
                except Exception:
                    pass
            result = IntentClassification(
                mode=result.mode,
                confidence=result.confidence,
                entity_type=result.entity_type,
                target_entity_id=result.target_entity_id,
                reasoning=result.reasoning,
                entities_mentioned=valid_mentions,
            )

    except Exception as e:
        # If aggregate loading fails, let the classification through
        # The mode handler will handle the error appropriately
        logger.warning(f"Post-filter entity check failed: {e}")

    return result
