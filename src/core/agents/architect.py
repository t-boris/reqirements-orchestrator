"""
Software Architect Agent - Technical validation and component mapping.

This agent ensures technical coherence of requirements, identifies
components, and detects conflicts.
"""

import autogen

from src.core.agents.prompts import SOFTWARE_ARCHITECT_PROMPT
from src.core.agents.tools import TOOL_DEFINITIONS


class SoftwareArchitect:
    """
    Software Architect agent - technical guardian.

    Responsibilities:
    - Identify required components for each story
    - Validate against non-functional requirements
    - Detect technical conflicts
    - Create risk nodes for technical concerns
    """

    def __init__(
        self,
        llm_config: dict,
        system_prompt: str | None = None,
    ) -> None:
        """
        Initialize Software Architect agent.

        Args:
            llm_config: AutoGen LLM configuration.
            system_prompt: Custom system prompt (uses default if None).
        """
        prompt = system_prompt if system_prompt else SOFTWARE_ARCHITECT_PROMPT
        self._agent = autogen.AssistantAgent(
            name="SoftwareArchitect",
            system_message=prompt,
            llm_config={
                **llm_config,
                "functions": [t["function"] for t in TOOL_DEFINITIONS],
            },
        )

    @property
    def agent(self) -> autogen.AssistantAgent:
        """Get the underlying AutoGen agent."""
        return self._agent

    def get_analysis_prompt(self, story_context: str) -> str:
        """
        Generate a prompt for analyzing a new story.

        Args:
            story_context: Context about the story to analyze.

        Returns:
            Prompt for technical analysis.
        """
        return f"""Please analyze this requirement from a technical perspective:

{story_context}

Consider:
1. What components does this require?
2. Are there any NFR concerns (security, performance, scalability)?
3. Does this conflict with any existing requirements?
4. What technical risks should we track?

Propose the necessary graph operations (add_node, add_edge) to capture your analysis.
"""
