"""Prompt builder with provider overlays and logging."""

import json
import logging
import hashlib
import re
from typing import Any

from src.llm.types import LLMProvider, Message, MessageRole
from src.llm.prompts.templates import (
    ANALYST_SYSTEM_BASE,
    EXTRACTION_TEMPLATE,
    VALIDATION_TEMPLATE,
    QUESTIONING_TEMPLATE,
)
from src.llm.prompts.overlays import (
    get_system_overlay,
    get_extraction_overlay,
    apply_overlay,
)

logger = logging.getLogger(__name__)

# Fields to redact in logs
REDACT_FIELDS = {"api_key", "token", "secret", "password", "credential"}

def _redact_secrets(text: str) -> str:
    """Redact potential secrets from text for logging."""
    # Simple redaction - in production, use more sophisticated detection
    for field in REDACT_FIELDS:
        if field in text.lower():
            # Redact values that look like secrets
            pattern = rf'({field}["\']?\s*[:=]\s*["\']?)([^"\'\s]+)'
            text = re.sub(pattern, r'\1[REDACTED]', text, flags=re.IGNORECASE)
    return text

def _prompt_hash(text: str) -> str:
    """Generate short hash for prompt identification."""
    return hashlib.sha256(text.encode()).hexdigest()[:8]


class PromptBuilder:
    """Build prompts with provider-specific overlays.

    Usage:
        builder = PromptBuilder(provider=LLMProvider.GEMINI)
        messages = builder.build_extraction_prompt(
            ticket_type="Story",
            draft={"summary": "..."},
            missing_fields=["acceptance_criteria"],
            conversation="User said...",
        )
    """

    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def _log_prompt(self, prompt_type: str, content: str):
        """Log assembled prompt with redaction."""
        redacted = _redact_secrets(content)
        prompt_hash = _prompt_hash(content)
        logger.debug(
            f"Assembled {prompt_type} prompt",
            extra={
                "prompt_type": prompt_type,
                "prompt_hash": prompt_hash,
                "provider": self.provider.value,
                "content_preview": redacted[:200] + "..." if len(redacted) > 200 else redacted,
            }
        )

    def build_system_prompt(self) -> str:
        """Build system prompt with provider overlay."""
        overlay = get_system_overlay(self.provider)
        prompt = apply_overlay(ANALYST_SYSTEM_BASE, overlay)
        self._log_prompt("system", prompt)
        return prompt

    def build_extraction_prompt(
        self,
        ticket_type: str,
        draft: dict[str, Any] | None,
        missing_fields: list[str],
        conversation: str,
    ) -> list[Message]:
        """Build extraction prompt messages."""
        system = self.build_system_prompt()

        user_content = EXTRACTION_TEMPLATE.format(
            ticket_type=ticket_type,
            draft_json=json.dumps(draft, indent=2) if draft else "{}",
            missing_fields=", ".join(missing_fields) if missing_fields else "none",
            messages=conversation,
        )

        # Apply extraction overlay
        overlay = get_extraction_overlay(self.provider)
        user_content = apply_overlay(user_content, overlay)

        self._log_prompt("extraction", user_content)

        return [
            Message(role=MessageRole.SYSTEM, content=system),
            Message(role=MessageRole.USER, content=user_content),
        ]

    def build_validation_prompt(
        self,
        ticket_type: str,
        draft: dict[str, Any] | None,
        missing_fields: list[str],
    ) -> list[Message]:
        """Build validation prompt messages."""
        system = self.build_system_prompt()

        user_content = VALIDATION_TEMPLATE.format(
            ticket_type=ticket_type,
            draft_json=json.dumps(draft, indent=2) if draft else "{}",
            missing_fields=", ".join(missing_fields) if missing_fields else "none",
        )

        self._log_prompt("validation", user_content)

        return [
            Message(role=MessageRole.SYSTEM, content=system),
            Message(role=MessageRole.USER, content=user_content),
        ]

    def build_questioning_prompt(
        self,
        ticket_type: str,
        draft: dict[str, Any] | None,
        missing_fields: list[str],
    ) -> list[Message]:
        """Build questioning prompt messages."""
        system = self.build_system_prompt()

        user_content = QUESTIONING_TEMPLATE.format(
            ticket_type=ticket_type,
            draft_json=json.dumps(draft, indent=2) if draft else "{}",
            missing_fields=", ".join(missing_fields) if missing_fields else "none",
        )

        self._log_prompt("questioning", user_content)

        return [
            Message(role=MessageRole.SYSTEM, content=system),
            Message(role=MessageRole.USER, content=user_content),
        ]


def get_prompt_builder(provider: LLMProvider) -> PromptBuilder:
    """Get a prompt builder for the specified provider."""
    return PromptBuilder(provider)
