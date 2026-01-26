"""Extraction package - extracts requirements from conversations.

Re-exports main entry points:
- extraction_node: Main graph node for draft extraction
- extract_multi_items_from_review: Extract multiple items from review text
"""
from src.graph.nodes.extraction.node import extraction_node
from src.graph.nodes.extraction.review import extract_multi_items_from_review

# Also expose internal helpers for backward compatibility
from src.graph.nodes.extraction.draft import (
    format_channel_context as _format_channel_context,
    detect_reference_to_prior_content as _detect_reference_to_prior_content,
)
from src.graph.nodes.extraction.conflict import (
    detect_value_conflict,
    store_and_signal_conflicts as _store_and_signal_conflicts,
)

__all__ = [
    "extraction_node",
    "extract_multi_items_from_review",
    # Internal helpers (underscore prefix indicates internal use)
    "_format_channel_context",
    "_detect_reference_to_prior_content",
    "detect_value_conflict",
    "_store_and_signal_conflicts",
]
