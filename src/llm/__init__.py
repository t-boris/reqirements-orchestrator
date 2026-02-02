"""LLM client module - Provider-agnostic LLM access.

Uses LiteLLM for multi-provider abstraction and Instructor for structured output.
Ref: RESEARCH.md - Standard Stack
"""

from src.llm.client import get_llm_client, safe_parse_json, structured_completion

__all__ = ["get_llm_client", "structured_completion", "safe_parse_json"]
