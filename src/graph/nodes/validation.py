"""Validation node - checks draft completeness and detects conflicts.

LLM-first approach: Uses LLM for semantic validation,
falls back to rule-based checks for structural requirements.

Output: ValidationReport with missing_fields[], conflicts[], suggestions[]
Also runs persona-specific validators (Phase 9).
"""
import json
import logging
from typing import Any, Optional
from pydantic import BaseModel, Field

from src.schemas.state import AgentState, AgentPhase
from src.schemas.draft import TicketDraft
from src.llm import get_llm
from src.personas.types import PersonaName, ValidationFindings

logger = logging.getLogger(__name__)


class ValidationReport(BaseModel):
    """Detailed validation report for decision node."""
    is_valid: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    quality_score: int = 0  # 0-100, for prioritization


VALIDATION_PROMPT = '''You are validating a Jira ticket draft for completeness and quality.

Draft:
{draft_json}

Analyze this draft and provide a validation report as JSON:

{{
  "is_valid": true/false,  // Ready for preview?
  "missing_fields": ["field1", "field2"],  // Required but empty/insufficient
  "conflicts": ["description of conflict"],  // Contradictory information
  "suggestions": ["improvement suggestion"],  // Optional improvements
  "quality_score": 0-100  // Overall readiness score
}}

Minimum requirements for is_valid=true:
- title: Clear, concise (not empty)
- problem: Describes what needs solving (not empty)
- acceptance_criteria: At least 1 testable criterion

Check for:
- Logical conflicts between stated requirements
- Ambiguous or vague descriptions
- Missing context that would be needed

JSON response:'''


def rule_based_validation(draft: TicketDraft) -> ValidationReport:
    """Fallback rule-based validation.

    Used if LLM validation fails.
    """
    report = ValidationReport()

    # Check required fields
    if not draft.title.strip():
        report.missing_fields.append("title")
    if not draft.problem.strip():
        report.missing_fields.append("problem")
    if not draft.acceptance_criteria:
        report.missing_fields.append("acceptance_criteria (at least one)")

    # Check for constraint conflicts (same key, different values)
    seen_constraints = {}
    for c in draft.constraints:
        if c.key in seen_constraints and seen_constraints[c.key] != c.value:
            report.conflicts.append(
                f"Conflicting values for {c.key}: '{seen_constraints[c.key]}' vs '{c.value}'"
            )
        seen_constraints[c.key] = c.value

    # Calculate score
    total_fields = 3  # title, problem, AC
    filled_fields = sum([
        bool(draft.title.strip()),
        bool(draft.problem.strip()),
        bool(draft.acceptance_criteria),
    ])
    report.quality_score = int((filled_fields / total_fields) * 100)

    report.is_valid = len(report.missing_fields) == 0
    return report


async def run_persona_validators(
    draft: TicketDraft,
    persona: str,
    context: Optional[dict] = None,
) -> ValidationFindings:
    """Run validators for the current persona.

    Also runs silent validators based on topic detection.

    Args:
        draft: Ticket draft to validate.
        persona: Current persona name.
        context: Optional context dict.

    Returns:
        ValidationFindings with all findings.
    """
    from src.personas.config import PERSONA_VALIDATORS, SILENT_VALIDATORS
    from src.personas.validators import get_validator_registry
    from src.personas.detector import TopicDetector

    findings = ValidationFindings()
    registry = get_validator_registry()

    # Get current persona
    try:
        current_persona = PersonaName(persona)
    except ValueError:
        current_persona = PersonaName.PM

    # Run mandatory validators for current persona
    mandatory_names = PERSONA_VALIDATORS.get(current_persona, ())
    mandatory_validators = registry.get_by_names(mandatory_names)

    for validator in mandatory_validators:
        try:
            validator_findings = await validator.validate(draft, context)
            for f in validator_findings:
                findings.add(f)
        except Exception as e:
            logger.warning(f"Validator {validator.name} failed: {e}")

    # Run silent validators based on topic detection
    # Combine all text for detection
    draft_text = f"{draft.title} {draft.problem} {draft.proposed_solution}"
    detector = TopicDetector()
    detection = detector.detect(draft_text)

    # Security silent checks (if above threshold and not already Security persona)
    if current_persona != PersonaName.SECURITY:
        security_config = SILENT_VALIDATORS.get("security", {})
        if detection.security_score >= security_config.get("threshold", 0.75):
            silent_names = security_config.get("validators", ())
            silent_validators = registry.get_by_names(silent_names)
            for validator in silent_validators:
                if validator not in mandatory_validators:  # Don't run twice
                    try:
                        validator_findings = await validator.validate(draft, context)
                        for f in validator_findings:
                            findings.add(f)
                    except Exception as e:
                        logger.warning(f"Silent validator {validator.name} failed: {e}")

    # Architect silent checks (if above threshold and not already Architect persona)
    if current_persona != PersonaName.ARCHITECT:
        architect_config = SILENT_VALIDATORS.get("architect", {})
        if detection.architect_score >= architect_config.get("threshold", 0.60):
            silent_names = architect_config.get("validators", ())
            silent_validators = registry.get_by_names(silent_names)
            for validator in silent_validators:
                if validator not in mandatory_validators:
                    try:
                        validator_findings = await validator.validate(draft, context)
                        for f in validator_findings:
                            findings.add(f)
                    except Exception as e:
                        logger.warning(f"Silent validator {validator.name} failed: {e}")

    logger.info(
        "Persona validation complete",
        extra={
            "persona": persona,
            "total_findings": len(findings.findings),
            "blocking": findings.has_blocking,
        }
    )

    return findings


async def validation_node(state: AgentState) -> dict[str, Any]:
    """Validate draft and produce detailed report.

    - Uses LLM for semantic validation
    - Falls back to rule-based if LLM fails
    - Stores report in state for decision node

    Returns partial state update.
    """
    draft = state.get("draft")
    step_count = state.get("step_count", 0)

    if not draft:
        logger.warning("No draft to validate")
        return {
            "step_count": step_count + 1,
            "phase": AgentPhase.COLLECTING,
            "validation_report": ValidationReport(
                missing_fields=["draft (no content yet)"]
            ).model_dump(),
        }

    # Try LLM validation first
    try:
        draft_json = draft.model_dump_json(
            exclude={"evidence_links", "created_at", "updated_at", "id"}
        )
        prompt = VALIDATION_PROMPT.format(draft_json=draft_json)

        llm = get_llm()
        result = await llm.chat(prompt)
        response_text = result.text.strip()

        # Parse JSON response
        if response_text.startswith("```"):
            response_text = response_text.split("```")[1]
            if response_text.startswith("json"):
                response_text = response_text[4:]
            response_text = response_text.strip()

        report_data = json.loads(response_text)
        report = ValidationReport(**report_data)

        logger.info(
            "LLM validation complete",
            extra={
                "is_valid": report.is_valid,
                "missing_count": len(report.missing_fields),
                "quality_score": report.quality_score,
            }
        )

    except Exception as e:
        logger.warning(f"LLM validation failed, using rule-based: {e}")
        report = rule_based_validation(draft)

    # Run persona-specific validators (Phase 9)
    persona = state.get("persona", "pm")
    channel_context = state.get("channel_context")

    persona_findings: Optional[ValidationFindings] = None
    try:
        persona_findings = await run_persona_validators(
            draft=draft,
            persona=persona,
            context=channel_context,
        )

        # Merge blocking findings with is_valid
        if persona_findings.has_blocking:
            report.is_valid = False

    except Exception as e:
        logger.warning(f"Persona validation failed: {e}")

    # Determine next phase
    if report.is_valid:
        next_phase = AgentPhase.VALIDATING  # Move to decision
    else:
        next_phase = AgentPhase.COLLECTING  # Need more info

    return {
        "step_count": step_count + 1,
        "phase": next_phase,
        "validation_report": report.model_dump(),
        "validator_findings": persona_findings.model_dump() if persona_findings else None,
    }
