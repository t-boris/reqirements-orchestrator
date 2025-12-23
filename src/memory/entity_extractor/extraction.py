"""
LLM-based Entity Extraction Functions.

Extracts domain-specific entities from messages using LLM with context understanding.
"""

import json
from datetime import datetime
from typing import Any

import structlog

from src.graph.llm import get_llm
from src.memory.entity_extractor.types import ENTITY_TYPES, RELATIONSHIP_TYPES

logger = structlog.get_logger()


EXTRACTION_PROMPT = """You are a knowledge graph builder for a requirements management system.

Analyze the user message and extract domain-specific entities, their relationships, and identify knowledge gaps.

## Entity Types
{entity_types}

## Relationship Types
{relationship_types}

## Existing Knowledge Graph (entities already known)
{existing_entities}

## User Message
{message}

## Conversation Context
{context}

## Instructions

1. **Extract Entities**: Identify ALL entities from the message
   - If an entity matches an existing one, use the SAME name (for merging)
   - Add new attributes/details to existing entities
   - Create new entities for novel concepts

2. **Identify Relationships**: Find connections between entities
   - Connect new entities to existing ones where applicable
   - Use specific relationship types, not just "related_to"

3. **Detect Knowledge Gaps**: What information is MISSING?
   - Missing acceptance criteria for requirements
   - Undefined stakeholders for components
   - Missing priorities or timelines
   - Unclear dependencies

4. **Generate Questions**: Based on gaps, what should we ask?

Respond with valid JSON only:
{{
  "entities": [
    {{
      "name": "exact entity name",
      "type": "entity_type",
      "description": "detailed description",
      "attributes": {{"key": "value"}},
      "is_update": false
    }}
  ],
  "relationships": [
    {{
      "source": "entity_name_1",
      "target": "entity_name_2",
      "type": "relationship_type",
      "description": "why this relationship exists"
    }}
  ],
  "knowledge_gaps": [
    {{
      "entity": "entity_name or null for general",
      "gap_type": "missing_criteria|undefined_owner|no_priority|unclear_dependency|missing_detail",
      "description": "what information is missing"
    }}
  ],
  "suggested_questions": [
    "Question to fill a specific knowledge gap?"
  ]
}}
"""


async def extract_knowledge(
    message: str,
    existing_entities: list[dict[str, Any]] | None = None,
    context: list[dict[str, Any]] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Extract entities, relationships, and identify knowledge gaps from a message.

    Args:
        message: The user message to analyze.
        existing_entities: Entities already in the knowledge graph (for merging).
        context: Recent facts/context from memory.
        model: Optional model override.

    Returns:
        Dict with entities, relationships, knowledge_gaps, and suggested_questions.
    """
    empty_result = {
        "entities": [],
        "relationships": [],
        "knowledge_gaps": [],
        "suggested_questions": [],
    }

    if not message or len(message.strip()) < 10:
        return empty_result

    # Format entity types for prompt
    entity_types_text = "\n".join(
        f"- {etype}: {desc}" for etype, desc in ENTITY_TYPES.items()
    )

    # Format relationship types for prompt
    relationship_types_text = "\n".join(
        f"- {rtype}: {desc}" for rtype, desc in RELATIONSHIP_TYPES.items()
    )

    # Format existing entities for context
    existing_entities_text = "No entities in knowledge graph yet."
    if existing_entities:
        entity_items = []
        for e in existing_entities[:20]:  # Limit to 20 most relevant
            attrs = e.get("attributes", {})
            attr_str = f" ({', '.join(f'{k}={v}' for k, v in attrs.items())})" if attrs else ""
            entity_items.append(f"- [{e.get('type', 'unknown')}] {e.get('name', 'unnamed')}{attr_str}")
        if entity_items:
            existing_entities_text = "\n".join(entity_items)

    # Format context
    context_text = "No previous context."
    if context:
        context_items = []
        for item in context[:5]:
            content = item.get("content", item.get("fact", ""))
            if content:
                context_items.append(f"- {content}")
        if context_items:
            context_text = "\n".join(context_items)

    prompt = EXTRACTION_PROMPT.format(
        entity_types=entity_types_text,
        relationship_types=relationship_types_text,
        existing_entities=existing_entities_text,
        message=message,
        context=context_text,
    )

    try:
        llm = get_llm(model=model or "gpt-4o-mini")
        response = await llm.ainvoke(prompt)

        # Parse JSON response
        content = response.content.strip()

        # Handle markdown code blocks
        if content.startswith("```"):
            lines = content.split("\n")
            # Find closing ``` and extract content between
            end_idx = len(lines) - 1
            for i in range(len(lines) - 1, 0, -1):
                if lines[i].strip() == "```":
                    end_idx = i
                    break
            content = "\n".join(lines[1:end_idx])

        data = json.loads(content)

        # Validate entities
        valid_entities = []
        for entity in data.get("entities", []):
            if not isinstance(entity, dict):
                continue
            if not entity.get("name") or not entity.get("type"):
                continue
            if entity["type"] not in ENTITY_TYPES:
                entity["type"] = "requirement"

            valid_entities.append({
                "name": str(entity.get("name", ""))[:200],
                "type": entity.get("type"),
                "description": str(entity.get("description", ""))[:500],
                "attributes": entity.get("attributes", {}),
                "is_update": entity.get("is_update", False),
                "extracted_at": datetime.utcnow().isoformat(),
            })

        # Validate relationships
        valid_relationships = []
        entity_names = {e["name"] for e in valid_entities}
        existing_names = {e.get("name") for e in (existing_entities or [])}
        all_names = entity_names | existing_names

        for rel in data.get("relationships", []):
            if not isinstance(rel, dict):
                continue
            source = rel.get("source", "")
            target = rel.get("target", "")
            rel_type = rel.get("type", "")

            # Both entities must exist (or be newly created)
            if source and target and (source in all_names or target in all_names):
                valid_relationships.append({
                    "source": str(source)[:200],
                    "target": str(target)[:200],
                    "type": rel_type if rel_type in RELATIONSHIP_TYPES else "affects",
                    "description": str(rel.get("description", ""))[:300],
                })

        # Validate knowledge gaps
        valid_gaps = []
        for gap in data.get("knowledge_gaps", []):
            if not isinstance(gap, dict):
                continue
            valid_gaps.append({
                "entity": gap.get("entity"),
                "gap_type": str(gap.get("gap_type", "missing_detail"))[:50],
                "description": str(gap.get("description", ""))[:300],
            })

        # Get suggested questions
        questions = [
            str(q)[:500] for q in data.get("suggested_questions", [])[:5]
            if isinstance(q, str)
        ]

        result = {
            "entities": valid_entities,
            "relationships": valid_relationships,
            "knowledge_gaps": valid_gaps,
            "suggested_questions": questions,
        }

        logger.info(
            "knowledge_extracted",
            entity_count=len(valid_entities),
            relationship_count=len(valid_relationships),
            gap_count=len(valid_gaps),
            question_count=len(questions),
        )

        return result

    except json.JSONDecodeError as e:
        logger.warning("knowledge_extraction_json_error", error=str(e))
        return empty_result
    except Exception as e:
        logger.warning("knowledge_extraction_failed", error=str(e))
        return empty_result


# Backward compatibility alias
async def extract_entities(
    message: str,
    context: list[dict[str, Any]] | None = None,
    model: str | None = None,
) -> list[dict[str, Any]]:
    """Legacy function - extracts only entities without relationships."""
    result = await extract_knowledge(message, None, context, model)
    return result.get("entities", [])


async def extract_and_format_for_zep(
    message: str,
    existing_entities: list[dict[str, Any]] | None = None,
    context: list[dict[str, Any]] | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """
    Extract knowledge and format for storage in Zep memory.

    Returns metadata dict suitable for Zep message metadata, including:
    - entities: extracted entities
    - relationships: connections between entities
    - knowledge_gaps: identified missing information
    - suggested_questions: questions to fill gaps
    """
    knowledge = await extract_knowledge(message, existing_entities, context, model)

    if not knowledge.get("entities") and not knowledge.get("relationships"):
        return {}

    return {
        "entities": knowledge.get("entities", []),
        "relationships": knowledge.get("relationships", []),
        "knowledge_gaps": knowledge.get("knowledge_gaps", []),
        "suggested_questions": knowledge.get("suggested_questions", []),
        "entity_count": len(knowledge.get("entities", [])),
        "relationship_count": len(knowledge.get("relationships", [])),
        "gap_count": len(knowledge.get("knowledge_gaps", [])),
        "entity_types": list(set(e["type"] for e in knowledge.get("entities", []))),
    }
