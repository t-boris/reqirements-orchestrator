"""Context packet for LLM prompt injection."""
from pydantic import BaseModel


class ContextPacket(BaseModel):
    """Structured context delivered to LLM.

    Three sections correspond to three context layers:
    - canonical: Layer A (DB state)
    - history: Layer B (conversation with rendered blocks)
    - retrieved: Layer C (attachments, Jira)
    """

    header: str = ""
    """Mode and purpose header for context framing."""

    canonical: str = ""
    """Layer A: Canonical state from DB (decisions, workitems, registry)."""

    history: str = ""
    """Layer B: Working history with rendered blocks."""

    retrieved: str = ""
    """Layer C: Retrieval add-ons (attachments, Jira snapshots)."""

    total_tokens: int = 0
    """Estimated token count for budget tracking."""

    @property
    def is_empty(self) -> bool:
        """Check if packet has any content."""
        return not (self.canonical or self.history or self.retrieved)

    def to_prompt(self) -> str:
        """Convert to formatted prompt string.

        Format:
        === SYSTEM STATE ===
        [canonical]

        === CONVERSATION ===
        [history]

        === RETRIEVED ===
        [retrieved]
        """
        sections = []

        if self.header:
            sections.append(self.header)

        if self.canonical:
            sections.append(f"=== SYSTEM STATE ===\n{self.canonical}")

        if self.history:
            sections.append(f"=== CONVERSATION ===\n{self.history}")

        if self.retrieved:
            sections.append(f"=== RETRIEVED ===\n{self.retrieved}")

        return "\n\n".join(sections)

    def to_compact_prompt(self) -> str:
        """Convert to compact format without section headers.

        For simpler prompts that don't need full structure.
        """
        parts = []
        if self.canonical:
            parts.append(self.canonical)
        if self.history:
            parts.append(self.history)
        if self.retrieved:
            parts.append(self.retrieved)
        return "\n\n".join(parts)

    @classmethod
    def empty(cls) -> "ContextPacket":
        """Create empty context packet."""
        return cls()
