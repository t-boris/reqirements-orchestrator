"""PM persona validators.

Checks: scope, acceptance_criteria, risks, dependencies
PM is default persona - these always run.
"""
from typing import Optional

from src.schemas.draft import TicketDraft
from src.personas.types import PersonaName, ValidatorSeverity, ValidatorFinding
from src.personas.validators.base import BaseValidator, get_validator_registry


class ScopeValidator(BaseValidator):
    """Checks for clear scope definition."""

    def __init__(self) -> None:
        super().__init__("scope", PersonaName.PM)

    async def validate(
        self,
        draft: TicketDraft,
        context: Optional[dict] = None,
    ) -> list[ValidatorFinding]:
        findings = []

        # Check for scope creep indicators
        scope_creep_words = ["also", "additionally", "plus", "and also", "while we're at it"]
        content = f"{draft.problem} {draft.proposed_solution}".lower()

        creep_count = sum(1 for word in scope_creep_words if word in content)
        if creep_count >= 2:
            findings.append(self._make_finding(
                "001",
                ValidatorSeverity.WARN,
                "Multiple scope additions detected - consider splitting into separate tickets",
                fix_hint="Focus on single deliverable per ticket",
            ))

        # Check for vague scope
        vague_words = ["improve", "enhance", "optimize", "better", "more"]
        vague_count = sum(1 for word in vague_words if word in content)
        has_measurable = any(
            any(c.isdigit() for c in ac) or "%" in ac or "seconds" in ac.lower() or "ms" in ac.lower()
            for ac in draft.acceptance_criteria
        )

        if vague_count >= 2 and not has_measurable:
            findings.append(self._make_finding(
                "002",
                ValidatorSeverity.INFO,
                "Vague improvement language without measurable criteria",
                fix_hint="Add specific metrics or thresholds",
            ))

        return findings


class AcceptanceCriteriaValidator(BaseValidator):
    """Checks acceptance criteria quality."""

    def __init__(self) -> None:
        super().__init__("acceptance_criteria", PersonaName.PM)

    async def validate(
        self,
        draft: TicketDraft,
        context: Optional[dict] = None,
    ) -> list[ValidatorFinding]:
        findings = []

        # Check for testable criteria
        if not draft.acceptance_criteria:
            findings.append(self._make_finding(
                "001",
                ValidatorSeverity.BLOCK,
                "No acceptance criteria defined",
                fix_hint="Add at least one testable acceptance criterion",
            ))
            return findings

        # Check for untestable criteria
        untestable_words = ["should work", "works well", "good performance", "user-friendly"]
        for i, ac in enumerate(draft.acceptance_criteria):
            ac_lower = ac.lower()
            if any(word in ac_lower for word in untestable_words):
                findings.append(self._make_finding(
                    f"{i+1:03d}",
                    ValidatorSeverity.WARN,
                    f"AC {i+1} may not be testable: '{ac[:40]}...'",
                    fix_hint="Make criterion specific and verifiable",
                ))

        return findings


class RisksValidator(BaseValidator):
    """Checks for risk identification."""

    def __init__(self) -> None:
        super().__init__("risks", PersonaName.PM)

    async def validate(
        self,
        draft: TicketDraft,
        context: Optional[dict] = None,
    ) -> list[ValidatorFinding]:
        findings = []

        # Check for high-complexity indicators without risk section
        complexity_indicators = [
            "migration", "refactor", "replace", "rewrite",
            "integration", "third-party", "external",
        ]
        content = f"{draft.title} {draft.problem} {draft.proposed_solution}".lower()

        has_complexity = any(ind in content for ind in complexity_indicators)

        if has_complexity and not draft.risks:
            findings.append(self._make_finding(
                "001",
                ValidatorSeverity.INFO,
                "Complex work detected but no risks identified",
                fix_hint="Consider what could go wrong or block progress",
            ))

        return findings


class DependenciesValidator(BaseValidator):
    """Checks for dependency identification."""

    def __init__(self) -> None:
        super().__init__("dependencies", PersonaName.PM)

    async def validate(
        self,
        draft: TicketDraft,
        context: Optional[dict] = None,
    ) -> list[ValidatorFinding]:
        findings = []

        # Check for external dependency indicators
        external_indicators = [
            "api", "service", "team", "approval", "review",
            "design", "spec", "external", "third-party",
        ]
        content = f"{draft.problem} {draft.proposed_solution}".lower()

        has_external = any(ind in content for ind in external_indicators)

        if has_external and not draft.dependencies:
            findings.append(self._make_finding(
                "001",
                ValidatorSeverity.INFO,
                "External dependencies mentioned but not listed",
                fix_hint="List external teams, APIs, or approvals needed",
            ))

        return findings


# Register validators on module import
def _register_pm_validators() -> None:
    registry = get_validator_registry()
    registry.register(ScopeValidator())
    registry.register(AcceptanceCriteriaValidator())
    registry.register(RisksValidator())
    registry.register(DependenciesValidator())


_register_pm_validators()
