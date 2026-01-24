"""Question Engine components for conversation-driven workflows.

Phase 36: Question Engine - Conversation Driver

This package provides the core components for the Question Engine:
- AnswerMapper: Process button clicks (deterministic) and text replies (LLM-parsed)
- BudgetTracker: Enforce question limits to prevent over-questioning
- QuestionCatalog: Hybrid question generators (templates + LLM)
- ModeManager: Active/Passive conversation mode handling
"""

from src.questions.answer_mapper import (
    AnswerMapper,
    ButtonAnswerMapper,
    TextAnswerMapper,
    encode_button_action_id,
    encode_button_value,
)
from src.questions.budget_tracker import (
    BudgetExhaustedAction,
    BudgetTracker,
)
from src.questions.catalog import (
    ConflictQuestionTemplates,
    FieldQuestionGenerator,
    QuestionCatalog,
    ScopeQuestionTemplates,
)
from src.questions.mode_manager import (
    ModeManager,
    detect_activation_reason,
    MODE_TIMEOUT_MINUTES,
)
from src.questions.provider import (
    ProviderType,
    QuestionProvider,
)
from src.questions.catalog_provider import CatalogProvider
from src.questions.freeform_provider import FreeformProvider

__all__ = [
    # Answer mapping
    "AnswerMapper",
    "ButtonAnswerMapper",
    "TextAnswerMapper",
    "encode_button_action_id",
    "encode_button_value",
    # Budget tracking
    "BudgetExhaustedAction",
    "BudgetTracker",
    # Question catalog
    "QuestionCatalog",
    "ScopeQuestionTemplates",
    "ConflictQuestionTemplates",
    "FieldQuestionGenerator",
    # Mode management
    "ModeManager",
    "detect_activation_reason",
    "MODE_TIMEOUT_MINUTES",
    # Provider interface (Phase 37)
    "ProviderType",
    "QuestionProvider",
    "CatalogProvider",
    "FreeformProvider",
]
