"""
Knowledge Graph Visualization.

Builds graph data structures for D3.js visualization.
"""

from typing import Any

from src.memory.entity_extractor.types import RELATIONSHIP_COLORS, TYPE_COLORS


def build_knowledge_graph_data(
    knowledge_by_session: dict[str, dict[str, Any]],
    include_session_nodes: bool = False,
) -> dict[str, Any]:
    """
    Build knowledge graph structure from extracted knowledge.

    Args:
        knowledge_by_session: Dict mapping session_id to knowledge data containing:
            - entities: list of entity dicts
            - relationships: list of relationship dicts
            - knowledge_gaps: list of gap dicts
        include_session_nodes: If True, include session nodes and edges to them.
            Defaults to False as session nodes clutter the visualization.

    Returns:
        Graph data with nodes and edges for D3.js visualization.
    """
    nodes = []
    edges = []
    node_ids = {}  # Maps entity name -> node id
    node_id_set = set()

    for session_id, knowledge in knowledge_by_session.items():
        entities = knowledge.get("entities", [])
        relationships = knowledge.get("relationships", [])
        gaps = knowledge.get("knowledge_gaps", [])

        # Optionally add session node (disabled by default)
        if include_session_nodes and session_id not in node_id_set:
            nodes.append({
                "id": session_id,
                "label": session_id.replace("channel-", ""),
                "type": "session",
                "description": "Conversation session",
                "color": TYPE_COLORS["session"],
                "size": 15,
            })
            node_id_set.add(session_id)

        # Add entity nodes
        for entity in entities:
            entity_name = entity.get("name", "")
            entity_type = entity.get("type", "requirement")
            entity_id = f"{entity_type}_{entity_name.lower().replace(' ', '_')[:50]}"

            # Track name -> id mapping for relationships
            node_ids[entity_name] = entity_id

            # Add entity node if not exists
            if entity_id not in node_id_set:
                nodes.append({
                    "id": entity_id,
                    "label": entity_name[:30],
                    "type": entity_type,
                    "description": entity.get("description", entity_name),
                    "attributes": entity.get("attributes", {}),
                    "color": TYPE_COLORS.get(entity_type, "#64748b"),
                    "size": 10,
                })
                node_id_set.add(entity_id)

            # Optionally add edge from session to entity
            if include_session_nodes:
                edges.append({
                    "source": session_id,
                    "target": entity_id,
                    "type": "contains",
                    "label": "contains",
                    "color": RELATIONSHIP_COLORS["contains"],
                    "strength": 0.3,
                })

        # Add relationship edges
        for rel in relationships:
            source_name = rel.get("source", "")
            target_name = rel.get("target", "")
            rel_type = rel.get("type", "affects")

            source_id = node_ids.get(source_name)
            target_id = node_ids.get(target_name)

            if source_id and target_id:
                edges.append({
                    "source": source_id,
                    "target": target_id,
                    "type": rel_type,
                    "label": rel_type.replace("_", " "),
                    "description": rel.get("description", ""),
                    "color": RELATIONSHIP_COLORS.get(rel_type, "#64748b"),
                    "strength": 0.7,
                })

        # Add knowledge gap nodes
        for i, gap in enumerate(gaps):
            gap_id = f"gap_{session_id}_{i}"
            gap_entity = gap.get("entity")

            if gap_id not in node_id_set:
                nodes.append({
                    "id": gap_id,
                    "label": f"Gap: {gap.get('gap_type', 'unknown')[:15]}",
                    "type": "gap",
                    "description": gap.get("description", "Unknown gap"),
                    "gap_type": gap.get("gap_type"),
                    "color": TYPE_COLORS["gap"],
                    "size": 8,
                    "dashed": True,
                })
                node_id_set.add(gap_id)

            # Connect gap to entity if specified
            if gap_entity and gap_entity in node_ids:
                edges.append({
                    "source": node_ids[gap_entity],
                    "target": gap_id,
                    "type": "has_gap",
                    "label": "has gap",
                    "color": RELATIONSHIP_COLORS["has_gap"],
                    "strength": 0.5,
                    "dashed": True,
                })
            # If no specific entity, gap remains unconnected (floating)
            # This is cleaner than connecting to session node

    return {
        "nodes": nodes,
        "edges": edges,
        "metadata": {
            "total_entities": sum(
                len(k.get("entities", [])) for k in knowledge_by_session.values()
            ),
            "total_relationships": sum(
                len(k.get("relationships", [])) for k in knowledge_by_session.values()
            ),
            "total_gaps": sum(
                len(k.get("knowledge_gaps", [])) for k in knowledge_by_session.values()
            ),
            "sessions": list(knowledge_by_session.keys()),
        },
    }
