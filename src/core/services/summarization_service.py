"""
Summarization Service - Context compression for LLM.

Summarizes older graph nodes when context exceeds threshold,
preserving original data in database.
"""

from typing import TYPE_CHECKING

from src.core.graph.graph import RequirementsGraph
from src.core.graph.models import GraphNode, NodeStatus

if TYPE_CHECKING:
    from src.adapters.llm.protocol import LLMProtocol


class SummarizationService:
    """
    Service for compressing graph context.

    When the context string exceeds the token threshold,
    older nodes are summarized to reduce token count
    while preserving essential information.
    """

    def __init__(
        self,
        llm_client: "LLMProtocol",
        context_threshold_percent: int = 80,
        max_context_tokens: int = 128000,  # GPT-5 context window
    ) -> None:
        """
        Initialize summarization service.

        Args:
            llm_client: LLM client for generating summaries.
            context_threshold_percent: Trigger threshold (% of max context).
            max_context_tokens: Maximum context window size.
        """
        self._llm = llm_client
        self._threshold_percent = context_threshold_percent
        self._max_tokens = max_context_tokens

    @property
    def threshold_tokens(self) -> int:
        """Calculate token threshold for triggering summarization."""
        return int(self._max_tokens * self._threshold_percent / 100)

    def estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.

        Uses rough approximation of 4 chars per token.
        For production, use tiktoken or model-specific tokenizer.

        Args:
            text: Text to estimate.

        Returns:
            Estimated token count.
        """
        return len(text) // 4

    def needs_summarization(self, graph: RequirementsGraph) -> bool:
        """
        Check if graph context needs summarization.

        Args:
            graph: The graph to check.

        Returns:
            True if context exceeds threshold.
        """
        context = graph.to_context_string()
        tokens = self.estimate_tokens(context)
        return tokens > self.threshold_tokens

    async def summarize_graph(self, graph: RequirementsGraph) -> RequirementsGraph:
        """
        Summarize older nodes in the graph.

        Strategy:
        1. Identify candidates (old, synced, or low-priority nodes)
        2. Group related nodes
        3. Generate summaries via LLM
        4. Replace detailed descriptions with summaries

        Args:
            graph: The graph to summarize.

        Returns:
            Graph with summarized nodes.
        """
        candidates = self._identify_candidates(graph)

        if not candidates:
            return graph

        for node in candidates:
            if node.is_summarized:
                continue

            summary = await self._generate_summary(node)

            # Preserve original description
            node.original_description = node.description
            node.description = summary
            node.is_summarized = True

        return graph

    def _identify_candidates(self, graph: RequirementsGraph) -> list[GraphNode]:
        """
        Identify nodes that are good candidates for summarization.

        Prioritizes:
        - Already synced nodes (information preserved in Jira)
        - Older nodes (by created_at)
        - Nodes with long descriptions

        Args:
            graph: The graph to analyze.

        Returns:
            List of nodes to summarize, ordered by priority.
        """
        nodes = graph.get_all_nodes()

        # Score nodes for summarization priority
        scored = []
        for node in nodes:
            if node.is_summarized:
                continue

            score = 0

            # Synced nodes are safe to summarize
            if node.status == NodeStatus.SYNCED:
                score += 10

            # Long descriptions benefit most from summarization
            if len(node.description) > 500:
                score += 5

            # Older nodes are better candidates
            # (implicit in sort order if we sort by created_at)

            if score > 0:
                scored.append((score, node))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Return top candidates (summarize ~30% of eligible nodes)
        count = max(1, len(scored) // 3)
        return [node for _, node in scored[:count]]

    async def _generate_summary(self, node: GraphNode) -> str:
        """
        Generate a concise summary of a node.

        Args:
            node: The node to summarize.

        Returns:
            Summarized description.
        """
        if len(node.description) < 100:
            return node.description

        prompt = f"""Summarize this {node.type.value} in 1-2 sentences, preserving key requirements:

Title: {node.title}
Description: {node.description}

Summary:"""

        response = await self._llm.complete(prompt)
        return response.strip()

    def get_full_context(self, graph: RequirementsGraph) -> str:
        """
        Get full context with both summarized and original data.

        Useful for detailed analysis or exports.

        Args:
            graph: The graph to export.

        Returns:
            Complete context string with original descriptions.
        """
        lines = []
        for node in graph.get_all_nodes():
            lines.append(f"=== {node.type.value.upper()}: {node.title} ===")
            if node.is_summarized and node.original_description:
                lines.append(f"Summary: {node.description}")
                lines.append(f"Original: {node.original_description}")
            else:
                lines.append(f"Description: {node.description}")
            lines.append("")
        return "\n".join(lines)
