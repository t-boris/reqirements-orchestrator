"""Persona system - operational modes for the agent.

Personas are Policy + Lens (not "different chatbots"):
- prompt overlay: tone + priorities
- validation policy: extra checks to run
- tool preference: what to ask for, what to preview

Two orthogonal axes:
- persona controls voice and priorities
- validators control safety and correctness
"""
from src.personas.types import (
    PersonaName,
    PersonaReason,
    RiskTolerance,
    ValidatorSeverity,
    ValidatorFinding,
    ValidationFindings,
)
from src.personas.config import (
    PersonaConfig,
    PERSONAS,
    PERSONA_VALIDATORS,
    SILENT_VALIDATORS,
    SENSITIVE_OPS,
    get_persona,
    get_default_persona,
)

__all__ = [
    # Types
    "PersonaName",
    "PersonaReason",
    "RiskTolerance",
    "ValidatorSeverity",
    "ValidatorFinding",
    "ValidationFindings",
    # Config
    "PersonaConfig",
    "PERSONAS",
    "PERSONA_VALIDATORS",
    "SILENT_VALIDATORS",
    "SENSITIVE_OPS",
    "get_persona",
    "get_default_persona",
]
