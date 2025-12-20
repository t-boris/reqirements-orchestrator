"""
Product Manager Agent - Business value and story quality.

This agent ensures proper user story format, acceptance criteria,
and maintains the requirements hierarchy.
"""

import autogen

from src.core.agents.prompts import PRODUCT_MANAGER_PROMPT
from src.core.agents.tools import TOOL_DEFINITIONS


class ProductManager:
    """
    Product Manager agent - business value guardian.

    Responsibilities:
    - Translate requirements into proper user stories
    - Ensure acceptance criteria are defined
    - Maintain GOAL -> EPIC -> STORY hierarchy
    - Manage story status (DRAFT -> APPROVED)
    """

    def __init__(
        self,
        llm_config: dict,
        system_prompt: str | None = None,
    ) -> None:
        """
        Initialize Product Manager agent.

        Args:
            llm_config: AutoGen LLM configuration.
            system_prompt: Custom system prompt (uses default if None).
        """
        prompt = system_prompt if system_prompt else PRODUCT_MANAGER_PROMPT
        self._agent = autogen.AssistantAgent(
            name="ProductManager",
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

    def get_story_prompt(self, user_requirement: str) -> str:
        """
        Generate a prompt for creating a user story.

        Args:
            user_requirement: Raw requirement from user.

        Returns:
            Prompt for story creation.
        """
        return f"""Please analyze this requirement and create proper user story(ies):

"{user_requirement}"

For each story, ensure:
1. Clear actor (who is this for?)
2. Clear goal (what do they want to achieve?)
3. Clear benefit (why do they want this?)
4. Acceptance criteria (how do we know it's done?)

Propose the necessary graph operations (add_node, add_edge) to capture the requirements.
"""
