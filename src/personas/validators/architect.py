"""Architect persona validators.

Checks: boundaries, failure_modes, idempotency, scaling
Medium threshold (0.60) for silent activation.
"""
from typing import Optional

from src.schemas.draft import TicketDraft
from src.personas.types import PersonaName, ValidatorSeverity, ValidatorFinding
from src.personas.validators.base import BaseValidator, get_validator_registry


class BoundariesValidator(BaseValidator):
    """Checks for clear system/service boundaries."""

    def __init__(self) -> None:
        super().__init__("boundaries", PersonaName.ARCHITECT)

    async def validate(
        self,
        draft: TicketDraft,
        context: Optional[dict] = None,
    ) -> list[ValidatorFinding]:
        findings = []

        # Check for integration mentions without boundary definition
        integration_keywords = ["api", "service", "integration", "external", "webhook", "callback"]
        content = f"{draft.title} {draft.problem} {draft.proposed_solution}".lower()

        has_integration = any(kw in content for kw in integration_keywords)

        if has_integration:
            has_boundary_spec = any(
                "interface" in ac.lower() or
                "contract" in ac.lower() or
                "boundary" in ac.lower() or
                "schema" in ac.lower()
                for ac in draft.acceptance_criteria
            )
            if not has_boundary_spec:
                findings.append(self._make_finding(
                    "001",
                    ValidatorSeverity.INFO,
                    "Involves external integration but no interface/contract specified",
                    fix_hint="Add AC for API contract or interface definition",
                ))

        return findings


class FailureModesValidator(BaseValidator):
    """Checks for failure mode considerations."""

    def __init__(self) -> None:
        super().__init__("failure_modes", PersonaName.ARCHITECT)

    async def validate(
        self,
        draft: TicketDraft,
        context: Optional[dict] = None,
    ) -> list[ValidatorFinding]:
        findings = []

        # Check for distributed system patterns without failure handling
        distributed_keywords = ["queue", "async", "event", "message", "webhook", "retry"]
        content = f"{draft.title} {draft.problem} {draft.proposed_solution}".lower()

        has_distributed = any(kw in content for kw in distributed_keywords)

        if has_distributed:
            has_failure_handling = any(
                "error" in ac.lower() or
                "fail" in ac.lower() or
                "retry" in ac.lower() or
                "timeout" in ac.lower() or
                "fallback" in ac.lower()
                for ac in draft.acceptance_criteria
            )
            if not has_failure_handling:
                findings.append(self._make_finding(
                    "001",
                    ValidatorSeverity.WARN,
                    "Distributed operation without failure mode handling specified",
                    fix_hint="Add AC for error handling, retries, timeouts",
                ))

        return findings


class IdempotencyValidator(BaseValidator):
    """Checks for idempotency in write operations."""

    def __init__(self) -> None:
        super().__init__("idempotency", PersonaName.ARCHITECT)

    async def validate(
        self,
        draft: TicketDraft,
        context: Optional[dict] = None,
    ) -> list[ValidatorFinding]:
        findings = []

        # Check for write operations that should be idempotent
        write_keywords = ["create", "update", "write", "insert", "modify", "change"]
        retry_keywords = ["retry", "webhook", "queue", "event", "async"]

        content = f"{draft.title} {draft.problem} {draft.proposed_solution}".lower()

        has_write = any(kw in content for kw in write_keywords)
        has_retry_context = any(kw in content for kw in retry_keywords)

        if has_write and has_retry_context:
            has_idempotency = any(
                "idempotent" in ac.lower() or
                "dedup" in ac.lower() or
                "duplicate" in ac.lower()
                for ac in draft.acceptance_criteria
            )
            if not has_idempotency:
                findings.append(self._make_finding(
                    "001",
                    ValidatorSeverity.WARN,
                    "Write operation in retry-able context but no idempotency specified",
                    fix_hint="Add AC for idempotency key or deduplication",
                ))

        return findings


class ScalingValidator(BaseValidator):
    """Checks for scaling considerations."""

    def __init__(self) -> None:
        super().__init__("scaling", PersonaName.ARCHITECT)

    async def validate(
        self,
        draft: TicketDraft,
        context: Optional[dict] = None,
    ) -> list[ValidatorFinding]:
        findings = []

        # Check for bulk/batch operations without scaling consideration
        scale_keywords = ["bulk", "batch", "all", "mass", "import", "export", "sync"]
        content = f"{draft.title} {draft.problem} {draft.proposed_solution}".lower()

        has_scale_op = any(kw in content for kw in scale_keywords)

        if has_scale_op:
            has_scale_consideration = any(
                "limit" in ac.lower() or
                "pagination" in ac.lower() or
                "batch size" in ac.lower() or
                "rate limit" in ac.lower()
                for ac in draft.acceptance_criteria
            )
            if not has_scale_consideration:
                findings.append(self._make_finding(
                    "001",
                    ValidatorSeverity.INFO,
                    "Bulk operation without scale limits specified",
                    fix_hint="Add AC for batch size, pagination, or rate limits",
                ))

        return findings


# Register validators on module import
def _register_architect_validators() -> None:
    registry = get_validator_registry()
    registry.register(BoundariesValidator())
    registry.register(FailureModesValidator())
    registry.register(IdempotencyValidator())
    registry.register(ScalingValidator())


_register_architect_validators()
