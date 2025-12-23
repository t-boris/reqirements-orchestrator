"""
Entity and Relationship Type Definitions.

Domain-specific types for requirements management knowledge extraction.
"""

# Domain-specific entity types for requirements management
ENTITY_TYPES = {
    "requirement": "A functional or non-functional requirement",
    "constraint": "A limitation or restriction on the system",
    "acceptance_criteria": "Conditions that must be met for acceptance",
    "risk": "A potential problem or threat",
    "dependency": "Something the system depends on",
    "stakeholder": "A person or role involved in the project",
    "component": "A system component or module",
    "integration": "An external system or API integration",
    "data_entity": "A data object or database entity",
    "user_action": "An action a user can perform",
    "business_rule": "A business logic rule or policy",
    "priority": "Priority level (high, medium, low, critical)",
    "timeline": "A deadline or time constraint",
    "technology": "A specific technology, framework, or tool",
}

# Relationship types between entities
RELATIONSHIP_TYPES = {
    "requires": "Entity A requires Entity B to function",
    "implements": "Entity A implements Entity B",
    "depends_on": "Entity A depends on Entity B",
    "conflicts_with": "Entity A conflicts with Entity B",
    "refines": "Entity A refines/details Entity B",
    "belongs_to": "Entity A is part of Entity B",
    "affects": "Entity A affects/impacts Entity B",
    "validates": "Entity A validates Entity B",
    "uses": "Entity A uses Entity B",
    "owned_by": "Entity A is owned/managed by Entity B (stakeholder)",
}

# Color mapping for entity types (used in visualization)
TYPE_COLORS = {
    "requirement": "#0284c7",      # Blue
    "constraint": "#dc2626",       # Red
    "acceptance_criteria": "#16a34a",  # Green
    "risk": "#ea580c",             # Orange
    "dependency": "#7c3aed",       # Purple
    "stakeholder": "#0891b2",      # Cyan
    "component": "#4f46e5",        # Indigo
    "integration": "#c026d3",      # Fuchsia
    "data_entity": "#65a30d",      # Lime
    "user_action": "#0d9488",      # Teal
    "business_rule": "#b91c1c",    # Dark red
    "priority": "#ca8a04",         # Yellow
    "timeline": "#6366f1",         # Violet
    "technology": "#64748b",       # Slate
    "session": "#374151",          # Gray
    "gap": "#f97316",              # Orange (for knowledge gaps)
}

# Edge colors by relationship type
RELATIONSHIP_COLORS = {
    "requires": "#dc2626",         # Red
    "implements": "#16a34a",       # Green
    "depends_on": "#7c3aed",       # Purple
    "conflicts_with": "#ef4444",   # Bright red
    "refines": "#0284c7",          # Blue
    "belongs_to": "#6366f1",       # Violet
    "affects": "#f59e0b",          # Amber
    "validates": "#10b981",        # Emerald
    "uses": "#8b5cf6",             # Purple
    "owned_by": "#0891b2",         # Cyan
    "contains": "#64748b",         # Slate (session -> entity)
    "has_gap": "#f97316",          # Orange (entity -> gap)
}
