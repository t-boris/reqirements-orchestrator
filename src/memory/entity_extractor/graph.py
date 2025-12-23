"""
In-Memory Knowledge Graph Management.

KnowledgeGraph class for managing entities, relationships, and gaps across messages.
"""

from datetime import datetime
from typing import Any


class KnowledgeGraph:
    """
    In-memory knowledge graph for a session.

    Manages entities, relationships, and gaps across messages.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.entities: dict[str, dict[str, Any]] = {}  # name -> entity
        self.relationships: list[dict[str, Any]] = []
        self.knowledge_gaps: list[dict[str, Any]] = []
        self.message_count = 0

    def get_entities_list(self) -> list[dict[str, Any]]:
        """Get all entities as a list."""
        return list(self.entities.values())

    def merge_knowledge(self, knowledge: dict[str, Any]) -> dict[str, Any]:
        """
        Merge new knowledge into the graph.

        Returns summary of changes:
        - new_entities: count of newly added entities
        - updated_entities: count of entities that were updated
        - new_relationships: count of new relationships
        - new_gaps: count of new gaps
        """
        new_entities = 0
        updated_entities = 0

        # Merge entities
        for entity in knowledge.get("entities", []):
            name = entity.get("name")
            if not name:
                continue

            if name in self.entities:
                # Update existing entity - merge attributes
                existing = self.entities[name]
                existing_attrs = existing.get("attributes", {})
                new_attrs = entity.get("attributes", {})
                existing["attributes"] = {**existing_attrs, **new_attrs}
                existing["description"] = entity.get("description") or existing.get("description")
                existing["last_updated"] = datetime.utcnow().isoformat()
                updated_entities += 1
            else:
                # Add new entity
                self.entities[name] = entity
                new_entities += 1

        # Add relationships (avoid duplicates)
        existing_rels = {
            (r["source"], r["target"], r["type"]) for r in self.relationships
        }
        new_rels = 0
        for rel in knowledge.get("relationships", []):
            rel_key = (rel.get("source"), rel.get("target"), rel.get("type"))
            if rel_key not in existing_rels:
                self.relationships.append(rel)
                existing_rels.add(rel_key)
                new_rels += 1

        # Add gaps (filter resolved ones)
        resolved_entities = set(self.entities.keys())
        new_gaps = 0
        for gap in knowledge.get("knowledge_gaps", []):
            # Don't add gaps for entities that now exist
            gap_entity = gap.get("entity")
            if gap_entity and gap_entity in resolved_entities:
                continue
            self.knowledge_gaps.append(gap)
            new_gaps += 1

        self.message_count += 1

        return {
            "new_entities": new_entities,
            "updated_entities": updated_entities,
            "new_relationships": new_rels,
            "new_gaps": new_gaps,
            "total_entities": len(self.entities),
            "total_relationships": len(self.relationships),
            "total_gaps": len(self.knowledge_gaps),
        }

    def get_suggested_questions(self) -> list[str]:
        """Get questions based on current knowledge gaps."""
        questions = []
        for gap in self.knowledge_gaps[-5:]:  # Last 5 gaps
            gap_type = gap.get("gap_type", "")
            entity = gap.get("entity")
            desc = gap.get("description", "")

            if gap_type == "missing_criteria" and entity:
                questions.append(f"What are the acceptance criteria for '{entity}'?")
            elif gap_type == "undefined_owner" and entity:
                questions.append(f"Who is responsible for '{entity}'?")
            elif gap_type == "no_priority" and entity:
                questions.append(f"What is the priority of '{entity}'?")
            elif gap_type == "unclear_dependency" and entity:
                questions.append(f"What does '{entity}' depend on?")
            elif desc:
                questions.append(f"Can you clarify: {desc}")

        return questions[:5]

    def to_dict(self) -> dict[str, Any]:
        """Export graph as dictionary for storage/visualization."""
        return {
            "session_id": self.session_id,
            "entities": list(self.entities.values()),
            "relationships": self.relationships,
            "knowledge_gaps": self.knowledge_gaps,
            "message_count": self.message_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeGraph":
        """Create graph from dictionary."""
        graph = cls(data.get("session_id", "unknown"))
        for entity in data.get("entities", []):
            if entity.get("name"):
                graph.entities[entity["name"]] = entity
        graph.relationships = data.get("relationships", [])
        graph.knowledge_gaps = data.get("knowledge_gaps", [])
        graph.message_count = data.get("message_count", 0)
        return graph


# Global cache for knowledge graphs (per session)
_knowledge_graphs: dict[str, KnowledgeGraph] = {}


def get_knowledge_graph(session_id: str) -> KnowledgeGraph:
    """Get or create knowledge graph for a session."""
    if session_id not in _knowledge_graphs:
        _knowledge_graphs[session_id] = KnowledgeGraph(session_id)
    return _knowledge_graphs[session_id]


def clear_knowledge_graph(session_id: str) -> None:
    """Clear knowledge graph for a session."""
    if session_id in _knowledge_graphs:
        del _knowledge_graphs[session_id]
