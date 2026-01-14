"""Persona type definitions.

Personas are operational modes (Policy + Lens), not "different chatbots".
Two orthogonal axes:
- persona -> presentation + emphasis (voice, priorities)
- validators -> risk detection + correctness (safety checks)
"""
from enum import Enum
from typing import Literal, Optional
from pydantic import BaseModel, Field


class PersonaName(str, Enum):
    """Available personas."""
    PM = "pm"
    SECURITY = "security"
    ARCHITECT = "architect"


class PersonaReason(str, Enum):
    """Why persona was activated."""
    DEFAULT = "default"      # PM is always default
    EXPLICIT = "explicit"    # User triggered (@security, /persona)
    DETECTED = "detected"    # Topic detection triggered


class RiskTolerance(str, Enum):
    """Persona risk tolerance level."""
    STRICT = "strict"        # Block on any concern
    MODERATE = "moderate"    # Warn but allow proceed


class ValidatorSeverity(str, Enum):
    """Validator finding severity."""
    BLOCK = "block"   # Must resolve before proceeding
    WARN = "warn"     # Should address but can proceed
    INFO = "info"     # Informational only


class ValidatorFinding(BaseModel):
    """Single finding from a validator."""
    id: str = Field(..., description="Finding ID for audit (e.g., SEC-RET-001)")
    severity: ValidatorSeverity
    message: str = Field(..., max_length=100, description="<=1 line description")
    fix_hint: Optional[str] = Field(None, max_length=100, description="Optional fix suggestion")
    validator: str = Field(..., description="Which validator produced this")
    persona: PersonaName = Field(..., description="Which persona owns this validator")


class ValidationFindings(BaseModel):
    """Collection of findings from all validators."""
    findings: list[ValidatorFinding] = Field(default_factory=list)
    has_blocking: bool = False  # True if any BLOCK severity

    def add(self, finding: ValidatorFinding) -> None:
        """Add a finding."""
        self.findings.append(finding)
        if finding.severity == ValidatorSeverity.BLOCK:
            self.has_blocking = True

    def by_severity(self, severity: ValidatorSeverity) -> list[ValidatorFinding]:
        """Get findings by severity."""
        return [f for f in self.findings if f.severity == severity]

    def by_persona(self, persona: PersonaName) -> list[ValidatorFinding]:
        """Get findings by persona."""
        return [f for f in self.findings if f.persona == persona]
