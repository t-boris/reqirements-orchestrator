"""
LLM-based Entity Extraction and Knowledge Graph Management.

Re-exports all public functions and classes from submodules.
"""

from src.memory.entity_extractor.extraction import (
    EXTRACTION_PROMPT,
    extract_and_format_for_zep,
    extract_entities,
    extract_knowledge,
)
from src.memory.entity_extractor.graph import (
    KnowledgeGraph,
    clear_knowledge_graph,
    get_knowledge_graph,
)
from src.memory.entity_extractor.types import (
    ENTITY_TYPES,
    RELATIONSHIP_COLORS,
    RELATIONSHIP_TYPES,
    TYPE_COLORS,
)
from src.memory.entity_extractor.visualization import build_knowledge_graph_data

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
