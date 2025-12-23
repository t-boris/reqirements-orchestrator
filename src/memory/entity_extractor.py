"""
LLM-based Entity Extraction and Knowledge Graph Management.

Re-exports from entity_extractor/ package for backward compatibility.
"""

# Re-export everything from the package
from src.memory.entity_extractor import *  # noqa: F401, F403
from src.memory.entity_extractor import (
    ENTITY_TYPES,
    EXTRACTION_PROMPT,
    RELATIONSHIP_COLORS,
    RELATIONSHIP_TYPES,
    TYPE_COLORS,
    KnowledgeGraph,
    build_knowledge_graph_data,
    clear_knowledge_graph,
    extract_and_format_for_zep,
    extract_entities,
    extract_knowledge,
    get_knowledge_graph,
)

__all__ = [
    # Types
    "ENTITY_TYPES",
    "RELATIONSHIP_TYPES",
    "TYPE_COLORS",
    "RELATIONSHIP_COLORS",
    # Extraction
    "EXTRACTION_PROMPT",
    "extract_knowledge",
    "extract_entities",
    "extract_and_format_for_zep",
    # Visualization
    "build_knowledge_graph_data",
    # Graph
    "KnowledgeGraph",
    "get_knowledge_graph",
    "clear_knowledge_graph",
]
