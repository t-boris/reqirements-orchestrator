"""Base validator interface for persona-specific checks.

Validators are pluggable - each persona has its own set.
Rule-based checks first (cheap heuristics), LLM calls only when needed.

Validators never auto-execute irreversible actions.
They may block workflow progression but never act autonomously.
"""
import logging
from abc import ABC, abstractmethod
from typing import Optional

from src.schemas.draft import TicketDraft
from src.personas.types import (
    PersonaName,
    ValidatorSeverity,
    ValidatorFinding,
    ValidationFindings,
)

logger = logging.getLogger(__name__)


class BaseValidator(ABC):
    """Base class for persona validators.

    Each validator:
    - Has a unique name (e.g., "authz", "scope")
    - Belongs to a persona (PM, Security, Architect)
    - Produces findings with severity (BLOCK, WARN, INFO)
    - Can run silently (no persona switch) based on detection
    """

    def __init__(self, name: str, persona: PersonaName) -> None:
        self.name = name
        self.persona = persona

    @abstractmethod
    async def validate(
        self,
        draft: TicketDraft,
        context: Optional[dict] = None,
    ) -> list[ValidatorFinding]:
        """Run validation on draft.

        Args:
            draft: Ticket draft to validate.
            context: Optional context (channel_context, etc.).

        Returns:
            List of findings (may be empty if no issues).
        """
        pass

    def _make_finding(
        self,
        id_suffix: str,
        severity: ValidatorSeverity,
        message: str,
        fix_hint: Optional[str] = None,
    ) -> ValidatorFinding:
        """Helper to create a finding with standard ID format."""
        # ID format: PERSONA-VALIDATOR-SUFFIX (e.g., SEC-AUTHZ-001)
        persona_prefix = {
            PersonaName.PM: "PM",
            PersonaName.SECURITY: "SEC",
            PersonaName.ARCHITECT: "ARCH",
        }[self.persona]

        finding_id = f"{persona_prefix}-{self.name.upper()}-{id_suffix}"

        return ValidatorFinding(
            id=finding_id,
            severity=severity,
            message=message[:100],  # Enforce max length
            fix_hint=fix_hint[:100] if fix_hint else None,
            validator=self.name,
            persona=self.persona,
        )


class ValidatorRegistry:
    """Registry of all validators, organized by persona."""

    def __init__(self) -> None:
        self._validators: dict[str, BaseValidator] = {}
        self._by_persona: dict[PersonaName, list[BaseValidator]] = {
            PersonaName.PM: [],
            PersonaName.SECURITY: [],
            PersonaName.ARCHITECT: [],
        }

    def register(self, validator: BaseValidator) -> None:
        """Register a validator."""
        self._validators[validator.name] = validator
        self._by_persona[validator.persona].append(validator)
        logger.debug(f"Registered validator: {validator.name} ({validator.persona.value})")

    def get(self, name: str) -> Optional[BaseValidator]:
        """Get validator by name."""
        return self._validators.get(name)

    def get_for_persona(self, persona: PersonaName) -> list[BaseValidator]:
        """Get all validators for a persona."""
        return self._by_persona[persona]

    def get_by_names(self, names: tuple[str, ...]) -> list[BaseValidator]:
        """Get validators by name list."""
        return [v for name in names if (v := self._validators.get(name))]


# Global registry
_registry: Optional[ValidatorRegistry] = None


def get_validator_registry() -> ValidatorRegistry:
    """Get the global validator registry."""
    global _registry
    if _registry is None:
        _registry = ValidatorRegistry()
        # Registration happens on import of validator modules
    return _registry
