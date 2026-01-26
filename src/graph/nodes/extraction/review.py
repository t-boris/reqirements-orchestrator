"""Review artifact extraction - extracts work items from review text.

Multi-item extraction uses a two-phase approach:
1. Extract item list (type + title only) - small response, no truncation
2. For each item, extract full description separately
"""
import json
import logging
import re
import uuid
from typing import Any

from src.llm import get_llm

logger = logging.getLogger(__name__)


# Phase 1: Extract just item list (lightweight, avoids truncation)
MULTI_ITEM_LIST_PROMPT = '''Analyze this review and list work items to create.

Review text:
{review_text}

Topic: {topic}
Requested scope: {scope}

SCOPE RULES:
- If scope contains "epic" (e.g., "epics_only", "2 epics"): ONLY extract Epics. Do NOT create Stories.
- If scope contains "story" or "full": Extract both Epics and Stories.
- If scope is "decision" or unclear: Extract only what was explicitly decided.

CRITICAL: Return ONLY a valid JSON array. No text before or after. No explanations.

Format:
[
  {{"type": "epic", "title": "Short title here"}},
  {{"type": "story", "title": "Short title here", "parent_index": 0}}
]

Rules:
- parent_index is the array index of the parent Epic (only for stories)
- Keep titles SHORT (under 80 chars)
- Do NOT include descriptions
- Do NOT auto-generate stories under epics unless scope explicitly asks for them

IMPORTANT: Your response must start with [ and end with ]. Nothing else.
'''

# Phase 2: Get full details for a single item
SINGLE_ITEM_DETAIL_PROMPT = '''Generate Jira ticket content for this work item.

Topic: {topic}
Item type: {item_type}
Item title: {item_title}

Context from review:
{review_excerpt}

Return JSON with full details:
{{"title": "Clear concise title", "description": "Detailed description with context, acceptance criteria if story"}}

Keep the description focused and actionable (2-4 paragraphs max).
'''


def _parse_json_response(response_text: str) -> Any:
    """Parse JSON from LLM response, handling common issues."""
    response_text = response_text.strip()

    # Handle markdown code blocks
    if response_text.startswith("```"):
        parts = response_text.split("```")
        if len(parts) >= 2:
            response_text = parts[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

    if not response_text:
        return None

    # Log raw response for debugging
    logger.debug(f"Parsing JSON response: {response_text[:300]}...")

    # Try parsing as-is first
    try:
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # Fix common LLM JSON issues
    fixed = response_text

    # Remove trailing commas before ] or }
    fixed = re.sub(r',\s*]', ']', fixed)
    fixed = re.sub(r',\s*}', '}', fixed)

    # Handle concatenated JSON objects (no array brackets)
    # e.g., '{"a":1} {"b":2}' -> '[{"a":1}, {"b":2}]'
    if fixed.startswith("{") and not fixed.startswith("["):
        # Find all JSON objects by matching balanced braces
        objects = []
        depth = 0
        start = None
        in_string = False
        escape = False

        for i, char in enumerate(fixed):
            if escape:
                escape = False
                continue
            if char == '\\':
                escape = True
                continue
            if char == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue

            if char == '{':
                if depth == 0:
                    start = i
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0 and start is not None:
                    objects.append(fixed[start:i+1])
                    start = None

        if len(objects) > 1:
            # Multiple objects found - wrap in array
            fixed = '[' + ', '.join(objects) + ']'
            logger.info(f"Wrapped {len(objects)} concatenated JSON objects into array")

    # Try to extract JSON array or object if there's extra text
    array_match = re.search(r'\[[\s\S]*\]', fixed)
    if array_match:
        fixed = array_match.group(0)
    else:
        obj_match = re.search(r'\{[\s\S]*\}', fixed)
        if obj_match:
            fixed = obj_match.group(0)

    # Remove trailing commas again after extraction
    fixed = re.sub(r',\s*]', ']', fixed)
    fixed = re.sub(r',\s*}', '}', fixed)

    try:
        return json.loads(fixed)
    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed even after fixes: {e}")
        logger.warning(f"Original response: {response_text[:500]}")
        logger.warning(f"After fixes: {fixed[:500]}")
        raise


async def extract_multi_items_from_review(review_text: str, scope: str, topic: str) -> list[dict]:
    """Extract multiple work items from review text using two-phase approach.

    Phase 1: Extract item list (type + title only) - small response, no truncation
    Phase 2: For each item, extract full description separately

    Returns list of items with:
    - id: UUID for internal tracking
    - type: "epic" or "story"
    - title: Item title
    - description: Item description
    - parent_id: For stories, references epic's item ID (not Jira key)

    Args:
        review_text: The review content to analyze
        scope: User-selected scope (decision, full, custom)
        topic: Topic of the review

    Returns:
        List of extracted items with UUIDs assigned
    """
    llm = get_llm()

    # Phase 1: Get item list (lightweight)
    list_prompt = MULTI_ITEM_LIST_PROMPT.format(
        review_text=review_text[:3000],
        topic=topic,
        scope=scope,
    )

    try:
        logger.info("Phase 1: Extracting item list from review")
        response_text = await llm.chat(list_prompt)
        logger.info(f"Phase 1 raw LLM response: {response_text[:500]}")
        item_list = _parse_json_response(response_text)

        if not isinstance(item_list, list):
            logger.warning(f"Expected list from item list extraction, got {type(item_list)}")
            return []

        if not item_list:
            logger.info("No items found in review")
            return []

        logger.info(f"Phase 1 complete: Found {len(item_list)} items")

        # Assign UUIDs and resolve parent relationships first
        items_with_ids = []
        for idx, item in enumerate(item_list):
            if not isinstance(item, dict):
                continue

            item_id = str(uuid.uuid4())
            item_type = item.get("type", "story").lower()
            if item_type not in ("epic", "story"):
                item_type = "story"

            items_with_ids.append({
                "id": item_id,
                "type": item_type,
                "title": item.get("title", "Untitled"),
                "description": "",  # Will be filled in Phase 2
                "parent_index": item.get("parent_index"),
            })

        # Resolve parent_index to parent_id
        for item in items_with_ids:
            parent_index = item.pop("parent_index", None)
            if parent_index is not None and isinstance(parent_index, int):
                if 0 <= parent_index < len(items_with_ids):
                    parent_item = items_with_ids[parent_index]
                    if parent_item["type"] == "epic":
                        item["parent_id"] = parent_item["id"]
                    else:
                        item["parent_id"] = None
                else:
                    item["parent_id"] = None
            else:
                item["parent_id"] = None

        # Phase 2: Get full details for each item (one at a time)
        logger.info(f"Phase 2: Extracting details for {len(items_with_ids)} items")
        review_excerpt = review_text[:2000]  # Context for detail extraction

        for i, item in enumerate(items_with_ids):
            try:
                detail_prompt = SINGLE_ITEM_DETAIL_PROMPT.format(
                    topic=topic,
                    item_type=item["type"],
                    item_title=item["title"],
                    review_excerpt=review_excerpt,
                )

                detail_response = await llm.chat(detail_prompt)
                logger.debug(f"Phase 2 raw LLM response for item {i}: {detail_response[:300]}")
                details = _parse_json_response(detail_response)

                if isinstance(details, dict):
                    # Update title if improved
                    if details.get("title"):
                        item["title"] = details["title"]
                    # Set description
                    item["description"] = details.get("description", "")

                logger.info(f"Phase 2: Extracted details for item {i+1}/{len(items_with_ids)}: {item['title'][:50]}")

            except Exception as e:
                logger.warning(f"Failed to extract details for item {i}: {e}")
                # Keep the item with empty description rather than failing entirely

        logger.info(
            "Extracted multi-items from review (two-phase)",
            extra={
                "item_count": len(items_with_ids),
                "epics": sum(1 for i in items_with_ids if i["type"] == "epic"),
                "stories": sum(1 for i in items_with_ids if i["type"] == "story"),
                "topic": topic,
            }
        )

        return items_with_ids

    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse multi-item extraction response: {e}")
        return []
    except Exception as e:
        logger.error(f"Multi-item extraction failed: {e}")
        return []
