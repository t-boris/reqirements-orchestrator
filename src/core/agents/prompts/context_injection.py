"""Context injection template for agent conversations."""

CONTEXT_INJECTION_TEMPLATE = """
=== CURRENT GRAPH STATE ===

{graph_context}

=== USER MESSAGE ===

{user_message}

=== INSTRUCTIONS ===

Analyze the user's message in the context of the current graph state.
Identify new requirements, updates to existing requirements, or questions.
Propose graph operations to accurately capture the requirements.
"""
