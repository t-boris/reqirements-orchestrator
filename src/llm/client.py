"""LLM client with structured output support.

Ref: RESEARCH.md - Pattern 2: Structured LLM Classification with Instructor
Ref: RESEARCH.md - Pattern 4: JSON Repair Fallback Layer
"""

import json
import logging
from functools import lru_cache
from typing import TypeVar

import instructor
import litellm
from json_repair import repair_json
from pydantic import BaseModel

from src.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


@lru_cache
def get_llm_client():
    """Get cached Instructor-patched LiteLLM client.

    Uses instructor.from_litellm() to add structured output support.
    The client can call any LLM provider supported by LiteLLM.
    """
    return instructor.from_litellm(litellm.completion)


async def structured_completion(
    response_model: type[T],
    messages: list[dict],
    *,
    max_retries: int | None = None,
    temperature: float | None = None,
) -> T:
    """Get structured LLM response with Pydantic validation.

    Args:
        response_model: Pydantic model class for response schema
        messages: OpenAI-format messages (role, content)
        max_retries: Override default retry count for validation failures
        temperature: Override default temperature

    Returns:
        Validated Pydantic model instance

    Raises:
        ValidationError: If response cannot be parsed after retries
    """
    settings = get_settings()
    client = get_llm_client()

    retries = max_retries if max_retries is not None else settings.llm_max_retries
    temp = temperature if temperature is not None else settings.llm_temperature

    logger.debug(
        f"LLM call: model={settings.llm_model_full}, "
        f"response_model={response_model.__name__}, "
        f"retries={retries}"
    )

    # Instructor handles validation errors by passing them back to LLM
    # and retrying automatically up to max_retries times
    response = client.chat.completions.create(
        model=settings.llm_model_full,
        response_model=response_model,
        max_retries=retries,
        temperature=temp,
        messages=messages,
        api_key=settings.llm_api_key,  # Explicitly pass API key for LiteLLM
    )

    logger.debug(f"LLM response: {response}")
    return response


def safe_parse_json(text: str) -> dict:
    """Parse JSON with repair fallback.

    Ref: RESEARCH.md - Pattern 4: JSON Repair Fallback Layer

    Args:
        text: Potentially malformed JSON string

    Returns:
        Parsed dictionary

    Raises:
        json.JSONDecodeError: If repair also fails
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("JSON parse failed, attempting repair")
        repaired = repair_json(text)
        return json.loads(repaired)
