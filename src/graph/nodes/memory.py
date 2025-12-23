"""Memory nodes for Zep integration."""

import structlog
from langchain_core.prompts import ChatPromptTemplate

from src.graph.state import (
    HumanDecision,
    IntentType,
    RequirementState,
    WorkflowPhase,
)

from src.graph.nodes.common import logger

# =============================================================================
# Memory Node (Zep Retrieval)
# =============================================================================

async def memory_node(state: RequirementState) -> dict:
    """
    Store current message and retrieve relevant context from Zep memory.

    1. Ensures session exists for this channel
    2. Extracts knowledge (entities, relationships, gaps) using LLM
    3. Merges knowledge into the session's knowledge graph
    4. Stores the message with extracted metadata in Zep
    5. Fetches relevant memories for context
    """
    from src.memory.zep_client import get_zep_client
    from src.memory.entity_extractor import (
        extract_knowledge,
        get_knowledge_graph,
    )

    channel_id = state.get("channel_id")
    message = state.get("message", "")
    user_id = state.get("user_id")

    logger.info("memory_node_start", channel_id=channel_id)

    session_id = f"channel-{channel_id}"
    knowledge_graph = get_knowledge_graph(session_id)
    extracted_metadata = {}
    suggested_questions = []

    try:
        zep = await get_zep_client()

        # 1. Ensure session exists (creates if not)
        session_id = await zep.ensure_session(channel_id, user_id)

        # Update knowledge graph session_id
        knowledge_graph.session_id = session_id

        # 2. Search for relevant memories first (for context)
        facts = []
        try:
            results = await zep.memory.search(
                session_id=session_id,
                text=message,
                limit=10,
            )
            for result in results:
                facts.append({
                    "content": result.get("content", ""),
                    "relevance": result.get("score", 0.0),
                    "timestamp": result.get("created_at"),
                })
        except Exception as search_err:
            logger.debug("memory_search_skipped", error=str(search_err))

        # 3. Extract knowledge from the message using LLM
        if message and len(message.strip()) >= 10:
            try:
                existing_entities = knowledge_graph.get_entities_list()
                knowledge = await extract_knowledge(
                    message=message,
                    existing_entities=existing_entities,
                    context=facts,
                    model="gpt-4o-mini",
                )

                # 4. Merge into knowledge graph
                merge_result = knowledge_graph.merge_knowledge(knowledge)
                logger.info(
                    "knowledge_merged",
                    session_id=session_id,
                    new_entities=merge_result.get("new_entities", 0),
                    updated_entities=merge_result.get("updated_entities", 0),
                    new_relationships=merge_result.get("new_relationships", 0),
                    total_entities=merge_result.get("total_entities", 0),
                )

                # Prepare metadata for Zep storage
                extracted_metadata = {
                    "entities": knowledge.get("entities", []),
                    "relationships": knowledge.get("relationships", []),
                    "knowledge_gaps": knowledge.get("knowledge_gaps", []),
                    "entity_count": len(knowledge.get("entities", [])),
                    "relationship_count": len(knowledge.get("relationships", [])),
                }

                # Get suggested questions from LLM or from gaps
                suggested_questions = knowledge.get("suggested_questions", [])
                if not suggested_questions:
                    suggested_questions = knowledge_graph.get_suggested_questions()

            except Exception as extract_err:
                logger.warning("knowledge_extraction_failed", error=str(extract_err))

        # 5. Store the incoming user message with extracted metadata
        if message:
            try:
                await zep.memory.add(
                    session_id=session_id,
                    messages=[
                        {
                            "role": "user",
                            "content": message,
                            "metadata": {
                                "user_id": user_id,
                                "channel_id": channel_id,
                                "is_mention": state.get("is_mention", False),
                                **extracted_metadata,
                            },
                        }
                    ],
                )
                logger.debug("message_stored_to_memory", session_id=session_id)
            except Exception as store_err:
                logger.warning("message_store_failed", error=str(store_err))

        logger.info(
            "memory_node_complete",
            fact_count=len(facts),
            session_id=session_id,
            entity_count=len(knowledge_graph.entities),
            gap_count=len(knowledge_graph.knowledge_gaps),
        )

        return {
            "zep_facts": facts,
            "zep_session_id": session_id,
            # New fields for knowledge graph
            "clarifying_questions": suggested_questions[:3],  # Limit to 3 questions
        }

    except Exception as e:
        logger.warning("memory_node_failed", error=str(e))
        return {
            "zep_facts": [],
            "zep_session_id": session_id,
            "clarifying_questions": [],
        }


# =============================================================================
# Memory Update Node
# =============================================================================

async def memory_update_node(state: RequirementState) -> dict:
    """
    Save the processed requirement to Zep memory.

    Stores the requirement as a fact for future retrieval.
    """
    from src.memory.zep_client import get_zep_client

    draft = state.get("draft")
    if not draft:
        return {}

    logger.info("updating_memory", channel_id=state.get("channel_id"))

    try:
        zep = await get_zep_client()
        session_id = state.get("zep_session_id", f"channel-{state.get('channel_id')}")

        # Add the requirement as a message to the session
        await zep.memory.add(
            session_id=session_id,
            messages=[
                {
                    "role": "assistant",
                    "content": f"Created requirement: {draft.get('title')} - {draft.get('description')}",
                    "metadata": {
                        "type": "requirement",
                        "issue_type": draft.get("issue_type"),
                        "jira_key": state.get("jira_issue_key"),
                        "channel_id": state.get("channel_id"),
                        "user_id": state.get("user_id"),
                    },
                }
            ],
        )

        logger.info("memory_updated", session_id=session_id)
        return {}

    except Exception as e:
        logger.warning("memory_update_failed", error=str(e))
        return {}

