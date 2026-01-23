"""Validation node - checks draft completeness and detects conflicts.

LLM-first approach: Uses LLM for semantic validation,
falls back to rule-based checks for structural requirements.

Output: ValidationReport with missing_fields[], conflicts[], suggestions[]
Also runs persona-specific validators (Phase 9).

Phase 28.4: Form-dependent validation based on issue type and lifecycle.
R5: Draft must have lifecycle - Cannot ask AC while in PLAN stage
R6: Validation depends on Draft form
"""
import json
import logging
from typing import TYPE_CHECKING, Any, Optional
from pydantic import BaseModel, Field

from src.schemas.state import AgentState, AgentPhase
from src.schemas.draft import TicketDraft, IssueType
from src.llm import get_llm
from src.personas.types import PersonaName, ValidationFindings

if TYPE_CHECKING:
    from src.schemas.structured_draft import StructuredDraft, DraftLifecycle

logger = logging.getLogger(__name__)


class ValidationReport(BaseModel):
    """Detailed validation report for decision node."""
    is_valid: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    quality_score: int = 0  # 0-100, for prioritization


# =============================================================================
# Form-Dependent Validation (Phase 28.4 - R5, R6)
# =============================================================================

def _get_validation_rules_for_type(issue_type: IssueType | None) -> dict:
    """Get validation rules based on issue type.

    R6: Validation depends on Draft form.
    - EPIC: goal/scope required, AC NOT required
    - STORY: title, problem, AC required
    - TASK/BUG: title, problem required, AC optional

    Args:
        issue_type: The issue type to get rules for.

    Returns:
        Dict with 'required', 'optional', and 'weight' keys.
    """
    if issue_type == IssueType.EPIC:
        return {
            "required": ["title", "problem"],  # problem = goal
            "optional": ["acceptance_criteria"],  # NOT required for epics
            "weight": {"title": 30, "problem": 50, "scope": 20},
        }
    elif issue_type == IssueType.STORY:
        return {
            "required": ["title", "problem", "acceptance_criteria"],
            "optional": [],
            "weight": {"title": 25, "problem": 25, "acceptance_criteria": 50},
        }
    else:  # TASK, BUG, or None (default to story rules)
        return {
            "required": ["title", "problem"],
            "optional": ["acceptance_criteria"],
            "weight": {"title": 40, "problem": 60},
        }


def validate_structured_draft(draft: "StructuredDraft") -> ValidationReport:
    """Validate StructuredDraft based on lifecycle and item types.

    R5: Lifecycle determines what to validate
    R6: Item type determines validation rules

    - EMPTY: Always invalid
    - SINGLE_ITEM: Validate primary item by its type
    - PLAN: Validate item count (>1) + each item by type (AC not required for epics)

    Args:
        draft: The StructuredDraft to validate.

    Returns:
        ValidationReport with validation results.
    """
    from src.schemas.structured_draft import DraftLifecycle, DraftKind

    report = ValidationReport()

    # EMPTY draft is always invalid
    if draft.lifecycle == DraftLifecycle.EMPTY or draft.is_empty():
        report.missing_fields.append("draft (no content yet)")
        report.quality_score = 0
        report.is_valid = False
        return report

    # PLAN drafts: validate item count
    if draft.kind == DraftKind.PLAN:
        if len(draft.items) < 2:
            report.missing_fields.append("plan_items (need at least 2 items for a plan)")

    # Validate each item based on its type
    total_score = 0
    items_validated = 0

    for item in draft.items:
        rules = _get_validation_rules_for_type(item.issue_type)

        # Check required fields for this item type
        if "title" in rules["required"] and not item.title.strip():
            report.missing_fields.append(f"title (for {item.issue_type.value})")

        if "problem" in rules["required"]:
            # problem is stored in either problem or goal field
            if not item.problem.strip() and not item.goal.strip():
                report.missing_fields.append(f"problem/goal (for {item.issue_type.value})")

        if "acceptance_criteria" in rules["required"]:
            # Only require AC for STORYs, not EPICs
            if not item.acceptance_criteria:
                report.missing_fields.append(f"acceptance_criteria (for {item.issue_type.value})")

        # Calculate quality score for this item
        item_score = 0
        weights = rules["weight"]

        if item.title.strip():
            item_score += weights.get("title", 30)
        if item.problem.strip() or item.goal.strip():
            item_score += weights.get("problem", 30)
        if item.acceptance_criteria or "acceptance_criteria" not in rules["required"]:
            item_score += weights.get("acceptance_criteria", 0)

        total_score += item_score
        items_validated += 1

    # Average score across all items
    if items_validated > 0:
        report.quality_score = int(total_score / items_validated)
    else:
        report.quality_score = 0

    # Draft is valid if no missing required fields
    report.is_valid = len(report.missing_fields) == 0

    return report


def transition_lifecycle(
    draft: "StructuredDraft",
    target: "DraftLifecycle",
    user_id: str,
) -> bool:
    """Transition draft to new lifecycle state with validation.

    Returns True if transition succeeded, False if invalid.
    Logs the transition to change_log.

    Args:
        draft: The StructuredDraft to transition.
        target: The target lifecycle state.
        user_id: The user making the transition.

    Returns:
        True if transition succeeded, False otherwise.
    """
    if not draft.can_transition_to(target):
        logger.warning(
            "Invalid lifecycle transition",
            extra={
                "from": draft.lifecycle.value,
                "to": target.value,
            }
        )
        return False

    old_lifecycle = draft.lifecycle
    draft.lifecycle = target
    draft.log_change(
        action="lifecycle_transition",
        user_id=user_id,
        details={"from": old_lifecycle.value, "to": target.value},
    )
    return True


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
    Phase 28.4: Now respects issue_type for form-dependent validation (R6).
    """
    report = ValidationReport()

    # Get type-aware validation rules (Phase 28.4 - R6)
    rules = _get_validation_rules_for_type(draft.issue_type)

    # Check required fields based on issue type
    if "title" in rules["required"] and not draft.title.strip():
        report.missing_fields.append("title")
    if "problem" in rules["required"] and not draft.problem.strip():
        report.missing_fields.append("problem")
    if "acceptance_criteria" in rules["required"] and not draft.acceptance_criteria:
        report.missing_fields.append("acceptance_criteria (at least one)")

    # Check for constraint conflicts (same key, different values)
    seen_constraints = {}
    for c in draft.constraints:
        if c.key in seen_constraints and seen_constraints[c.key] != c.value:
            report.conflicts.append(
                f"Conflicting values for {c.key}: '{seen_constraints[c.key]}' vs '{c.value}'"
            )
        seen_constraints[c.key] = c.value

    # Calculate score based on issue type weights
    weights = rules["weight"]
    total_weight = sum(weights.values())
    earned_weight = 0

    if draft.title.strip():
        earned_weight += weights.get("title", 30)
    if draft.problem.strip():
        earned_weight += weights.get("problem", 30)
    if draft.acceptance_criteria or "acceptance_criteria" not in rules["required"]:
        earned_weight += weights.get("acceptance_criteria", 0)

    report.quality_score = int((earned_weight / total_weight) * 100) if total_weight > 0 else 0

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
    - Phase 28.4: Supports StructuredDraft with form-dependent validation

    Returns partial state update.
    """
    draft = state.get("draft")
    structured_draft = state.get("structured_draft")
    step_count = state.get("step_count", 0)

    # Phase 28.4: Check for StructuredDraft first
    if structured_draft:
        logger.info(
            "Validating StructuredDraft",
            extra={
                "lifecycle": structured_draft.lifecycle.value,
                "kind": structured_draft.kind.value,
                "item_count": len(structured_draft.items),
            }
        )
        report = validate_structured_draft(structured_draft)

        # Determine next phase
        if report.is_valid:
            next_phase = AgentPhase.VALIDATING
        else:
            next_phase = AgentPhase.COLLECTING

        return {
            "step_count": step_count + 1,
            "phase": next_phase,
            "validation_report": report.model_dump(),
        }

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
        response_text = await llm.chat(prompt)
        response_text = response_text.strip()

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
