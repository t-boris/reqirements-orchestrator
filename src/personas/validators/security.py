"""Security persona validators.

Checks: authz, data_retention, secrets, least_privilege
Security warnings are "loud" - high threshold (0.75) for silent activation.
"""
import re
from typing import Optional

from src.schemas.draft import TicketDraft
from src.personas.types import PersonaName, ValidatorSeverity, ValidatorFinding
from src.personas.validators.base import BaseValidator, get_validator_registry


class AuthzValidator(BaseValidator):
    """Checks for authorization model in requirements."""

    def __init__(self) -> None:
        super().__init__("authz", PersonaName.SECURITY)

    async def validate(
        self,
        draft: TicketDraft,
        context: Optional[dict] = None,
    ) -> list[ValidatorFinding]:
        findings = []

        # Check for auth-related content without explicit authz model
        auth_keywords = ["api", "endpoint", "access", "user", "admin", "role"]
        content = f"{draft.title} {draft.problem} {draft.proposed_solution}".lower()

        has_auth_content = any(kw in content for kw in auth_keywords)
        has_authz_criteria = any(
            "auth" in ac.lower() or "permission" in ac.lower() or "role" in ac.lower()
            for ac in draft.acceptance_criteria
        )

        if has_auth_content and not has_authz_criteria:
            findings.append(self._make_finding(
                "001",
                ValidatorSeverity.WARN,
                "Feature involves user access but no authorization criteria specified",
                fix_hint="Add AC for who can access and with what permissions",
            ))

        return findings


class DataRetentionValidator(BaseValidator):
    """Checks for data retention considerations."""

    def __init__(self) -> None:
        super().__init__("data_retention", PersonaName.SECURITY)

    async def validate(
        self,
        draft: TicketDraft,
        context: Optional[dict] = None,
    ) -> list[ValidatorFinding]:
        findings = []

        # Check for data storage without retention policy
        storage_keywords = ["store", "save", "persist", "log", "record", "database", "cache"]
        pii_keywords = ["user", "email", "name", "address", "phone", "personal"]

        content = f"{draft.title} {draft.problem} {draft.proposed_solution}".lower()

        has_storage = any(kw in content for kw in storage_keywords)
        has_pii = any(kw in content for kw in pii_keywords)

        if has_storage and has_pii:
            has_retention_ac = any(
                "retention" in ac.lower() or "delete" in ac.lower() or "gdpr" in ac.lower()
                for ac in draft.acceptance_criteria
            )
            if not has_retention_ac:
                findings.append(self._make_finding(
                    "001",
                    ValidatorSeverity.WARN,
                    "Stores user data but no retention policy in acceptance criteria",
                    fix_hint="Add AC for data retention period and deletion",
                ))

        return findings


class SecretsValidator(BaseValidator):
    """Checks for secret/credential handling."""

    def __init__(self) -> None:
        super().__init__("secrets", PersonaName.SECURITY)

    # Patterns that suggest secrets in plain text
    SECRET_PATTERNS = [
        r"api[_-]?key",
        r"password",
        r"secret",
        r"token",
        r"credential",
        r"private[_-]?key",
    ]

    async def validate(
        self,
        draft: TicketDraft,
        context: Optional[dict] = None,
    ) -> list[ValidatorFinding]:
        findings = []

        content = f"{draft.title} {draft.problem} {draft.proposed_solution}"

        # Check if secrets mentioned but no secure handling specified
        has_secrets_mention = any(
            re.search(pattern, content, re.IGNORECASE)
            for pattern in self.SECRET_PATTERNS
        )

        if has_secrets_mention:
            has_secure_handling = any(
                "vault" in ac.lower() or
                "encrypt" in ac.lower() or
                "secure" in ac.lower() or
                "environment" in ac.lower()
                for ac in draft.acceptance_criteria
            )
            if not has_secure_handling:
                findings.append(self._make_finding(
                    "001",
                    ValidatorSeverity.BLOCK,
                    "Mentions secrets/credentials but no secure handling specified",
                    fix_hint="Add AC for secret storage (vault, env vars, encryption)",
                ))

        return findings


class LeastPrivilegeValidator(BaseValidator):
    """Checks for least privilege principle."""

    def __init__(self) -> None:
        super().__init__("least_privilege", PersonaName.SECURITY)

    async def validate(
        self,
        draft: TicketDraft,
        context: Optional[dict] = None,
    ) -> list[ValidatorFinding]:
        findings = []

        # Check for broad access patterns
        broad_access_patterns = ["admin", "full access", "all permissions", "superuser", "root"]
        content = f"{draft.title} {draft.problem} {draft.proposed_solution}".lower()

        for pattern in broad_access_patterns:
            if pattern in content:
                findings.append(self._make_finding(
                    "001",
                    ValidatorSeverity.WARN,
                    f"Mentions '{pattern}' - verify least privilege principle",
                    fix_hint="Specify minimum required permissions",
                ))
                break  # One finding is enough

        return findings


# Register validators on module import
def _register_security_validators() -> None:
    registry = get_validator_registry()
    registry.register(AuthzValidator())
    registry.register(DataRetentionValidator())
    registry.register(SecretsValidator())
    registry.register(LeastPrivilegeValidator())


_register_security_validators()
