"""Agent system prompts."""

from src.core.agents.prompts.graph_admin import GRAPH_ADMIN_PROMPT
from src.core.agents.prompts.architect import SOFTWARE_ARCHITECT_PROMPT
from src.core.agents.prompts.product_manager import PRODUCT_MANAGER_PROMPT
from src.core.agents.prompts.context_injection import CONTEXT_INJECTION_TEMPLATE

__all__ = [
    "GRAPH_ADMIN_PROMPT",
    "SOFTWARE_ARCHITECT_PROMPT",
    "PRODUCT_MANAGER_PROMPT",
    "CONTEXT_INJECTION_TEMPLATE",
]
