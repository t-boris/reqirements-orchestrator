"""Persona configuration - Policy + Lens definitions.

Each persona is a small overlay, not a giant prompt:
- name, goals (3-5 bullets)
- must_check validators
- questions_style, output_format
- risk_tolerance
"""
from dataclasses import dataclass, field
from typing import Optional

from src.personas.types import PersonaName, RiskTolerance


@dataclass(frozen=True)
class PersonaConfig:
    """Configuration for a single persona.

    Immutable config - persona behavior is deterministic.
    """
    name: PersonaName
    display_name: str
    emoji: str  # For subtle indicator on first 1-2 messages after switch
    goals: tuple[str, ...]  # 3-5 priority bullets
    must_check: tuple[str, ...]  # Validators that always run for this persona
    questions_style: str  # How this persona asks questions
    output_format: str  # How this persona formats responses
    risk_tolerance: RiskTolerance
    prompt_overlay: str  # Small prompt addition (not giant narrative)


# Persona validator mappings (two orthogonal mechanisms)
PERSONA_VALIDATORS: dict[PersonaName, tuple[str, ...]] = {
    PersonaName.PM: ("scope", "acceptance_criteria", "risks", "dependencies"),
    PersonaName.ARCHITECT: ("boundaries", "failure_modes", "idempotency", "scaling"),
    PersonaName.SECURITY: ("authz", "data_retention", "secrets", "least_privilege"),
}

# Silent validators - run based on topic detection (not persona switch)
SILENT_VALIDATORS: dict[str, dict] = {
    "security": {"threshold": 0.75, "validators": ("authz", "data_retention", "secrets")},
    "architect": {"threshold": 0.60, "validators": ("boundaries", "failure_modes")},
}

# Sensitive ops - always run Security validator regardless of detection
SENSITIVE_OPS: tuple[str, ...] = (
    "jira_create",
    "jira_update",
    "token_handling",
    "user_data_access",
    "content_storage",
    "channel_monitor",
)


# Persona definitions
PM_PERSONA = PersonaConfig(
    name=PersonaName.PM,
    display_name="Product Manager",
    emoji="📋",
    goals=(
        "Ensure requirements are clear and complete",
        "Identify missing acceptance criteria",
        "Flag scope risks and dependencies",
        "Prioritize user value",
        "Maintain timeline awareness",
    ),
    must_check=PERSONA_VALIDATORS[PersonaName.PM],
    questions_style="Focus on user stories and business value",
    output_format="Bullet lists with DoD section",
    risk_tolerance=RiskTolerance.MODERATE,
    prompt_overlay="""You are operating in PM mode. Prioritize:
- Clear problem statements
- Testable acceptance criteria
- Scope boundaries and dependencies
- User value and timeline risks""",
)

SECURITY_PERSONA = PersonaConfig(
    name=PersonaName.SECURITY,
    display_name="Security Analyst",
    emoji="🛡️",
    goals=(
        "Verify authorization model",
        "Check data retention policies",
        "Ensure least privilege access",
        "Validate audit trail requirements",
        "Flag secret/credential handling",
    ),
    must_check=PERSONA_VALIDATORS[PersonaName.SECURITY],
    questions_style="Direct questions about access, data, and permissions",
    output_format="Findings with severity and fix hints",
    risk_tolerance=RiskTolerance.STRICT,
    prompt_overlay="""You are operating in Security mode. Prioritize:
- Authorization and access control
- Data retention and privacy
- Secret management
- Audit trail and compliance""",
)

ARCHITECT_PERSONA = PersonaConfig(
    name=PersonaName.ARCHITECT,
    display_name="Technical Architect",
    emoji="🏗️",
    goals=(
        "Define system boundaries",
        "Identify failure modes",
        "Ensure idempotency where needed",
        "Plan for scaling requirements",
        "Specify observability needs",
    ),
    must_check=PERSONA_VALIDATORS[PersonaName.ARCHITECT],
    questions_style="Technical questions about design and failure cases",
    output_format="Architecture notes with trade-offs",
    risk_tolerance=RiskTolerance.MODERATE,
    prompt_overlay="""You are operating in Architect mode. Prioritize:
- Service boundaries and interfaces
- Failure modes and recovery
- Idempotency and consistency
- Scaling and observability""",
)


# Registry for lookup
PERSONAS: dict[PersonaName, PersonaConfig] = {
    PersonaName.PM: PM_PERSONA,
    PersonaName.SECURITY: SECURITY_PERSONA,
    PersonaName.ARCHITECT: ARCHITECT_PERSONA,
}


def get_persona(name: PersonaName) -> PersonaConfig:
    """Get persona configuration by name."""
    return PERSONAS[name]


def get_default_persona() -> PersonaConfig:
    """Get default persona (always PM)."""
    return PM_PERSONA
