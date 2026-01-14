"""Topic detection for persona-relevant content.

Detection methods in order of preference:
1. Explicit triggers (best): @security, @architect, /persona security
2. Heuristic keywords (good): "threat", "permission", "OAuth" → Security
3. LLM classifier (fine): only with logging and high confidence threshold

Topic drift solution: Multi-persona checks without switching voice.
Stay PM voice but run Security/Architect validators as silent checks.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

from src.personas.types import PersonaName
from src.personas.config import SILENT_VALIDATORS

logger = logging.getLogger(__name__)


# Heuristic keyword patterns for topic detection
SECURITY_KEYWORDS: tuple[str, ...] = (
    "threat", "permission", "oauth", "pii", "gdpr", "auth", "authz",
    "token", "secret", "credential", "access control", "encryption",
    "vulnerability", "penetration", "security", "compliance", "audit",
    "data retention", "privacy", "sensitive", "classified",
)

ARCHITECT_KEYWORDS: tuple[str, ...] = (
    "scaling", "queue", "idempotent", "idempotency", "architecture",
    "microservice", "api design", "latency", "throughput", "caching",
    "database", "schema", "migration", "failover", "disaster recovery",
    "observability", "monitoring", "tracing", "load balancer",
    "service mesh", "kubernetes", "container", "deployment",
)


@dataclass
class DetectionResult:
    """Result of topic detection."""
    security_score: float = 0.0  # 0.0 - 1.0
    architect_score: float = 0.0  # 0.0 - 1.0
    reasons: list[str] = field(default_factory=list)  # Matched terms/features
    explicit_trigger: Optional[PersonaName] = None  # If explicit @mention or /persona
    method: str = "none"  # "explicit", "heuristic", "llm"

    @property
    def should_switch_to_security(self) -> bool:
        """Check if should switch to Security persona."""
        if self.explicit_trigger == PersonaName.SECURITY:
            return True
        threshold = SILENT_VALIDATORS["security"]["threshold"]
        return self.security_score >= threshold

    @property
    def should_switch_to_architect(self) -> bool:
        """Check if should switch to Architect persona."""
        if self.explicit_trigger == PersonaName.ARCHITECT:
            return True
        threshold = SILENT_VALIDATORS["architect"]["threshold"]
        return self.architect_score >= threshold

    @property
    def suggested_persona(self) -> Optional[PersonaName]:
        """Get suggested persona based on detection."""
        if self.explicit_trigger:
            return self.explicit_trigger
        if self.should_switch_to_security:
            return PersonaName.SECURITY
        if self.should_switch_to_architect:
            return PersonaName.ARCHITECT
        return None


class TopicDetector:
    """Detects security and architecture topics in messages.

    Two-pass detection:
    1. Check for explicit triggers (@security, /persona)
    2. Heuristic keyword matching with scoring

    LLM classification deferred - heuristics sufficient for MVP.
    """

    # Explicit trigger patterns
    EXPLICIT_SECURITY_PATTERN = re.compile(
        r"@security|/persona\s+security",
        re.IGNORECASE
    )
    EXPLICIT_ARCHITECT_PATTERN = re.compile(
        r"@architect|/persona\s+architect",
        re.IGNORECASE
    )
    EXPLICIT_PM_PATTERN = re.compile(
        r"@pm|/persona\s+pm",
        re.IGNORECASE
    )

    def detect(self, message: str) -> DetectionResult:
        """Detect topic relevance in a message.

        Args:
            message: User message to analyze.

        Returns:
            DetectionResult with scores and explicit trigger if found.
        """
        result = DetectionResult()

        # Pass 1: Check explicit triggers (highest priority)
        if self.EXPLICIT_SECURITY_PATTERN.search(message):
            result.explicit_trigger = PersonaName.SECURITY
            result.security_score = 1.0
            result.method = "explicit"
            result.reasons.append("Explicit @security or /persona security trigger")
            logger.info("Explicit Security persona trigger detected")
            return result

        if self.EXPLICIT_ARCHITECT_PATTERN.search(message):
            result.explicit_trigger = PersonaName.ARCHITECT
            result.architect_score = 1.0
            result.method = "explicit"
            result.reasons.append("Explicit @architect or /persona architect trigger")
            logger.info("Explicit Architect persona trigger detected")
            return result

        if self.EXPLICIT_PM_PATTERN.search(message):
            result.explicit_trigger = PersonaName.PM
            result.method = "explicit"
            result.reasons.append("Explicit @pm or /persona pm trigger")
            logger.info("Explicit PM persona trigger detected")
            return result

        # Pass 2: Heuristic keyword matching
        message_lower = message.lower()

        # Security keywords
        security_matches = []
        for keyword in SECURITY_KEYWORDS:
            if keyword in message_lower:
                security_matches.append(keyword)

        # Architect keywords
        architect_matches = []
        for keyword in ARCHITECT_KEYWORDS:
            if keyword in message_lower:
                architect_matches.append(keyword)

        # Calculate scores (diminishing returns for multiple matches)
        if security_matches:
            # Score: 0.3 for first match, +0.15 for each additional (max 0.9)
            result.security_score = min(0.3 + 0.15 * (len(security_matches) - 1), 0.9)
            result.reasons.extend([f"Security keyword: {kw}" for kw in security_matches[:3]])
            result.method = "heuristic"

        if architect_matches:
            result.architect_score = min(0.3 + 0.15 * (len(architect_matches) - 1), 0.9)
            result.reasons.extend([f"Architect keyword: {kw}" for kw in architect_matches[:3]])
            result.method = "heuristic"

        if result.method == "heuristic":
            logger.debug(
                "Heuristic detection",
                extra={
                    "security_score": result.security_score,
                    "architect_score": result.architect_score,
                    "security_matches": len(security_matches),
                    "architect_matches": len(architect_matches),
                }
            )

        return result

    def detect_sensitive_op(self, operation: str) -> bool:
        """Check if operation is sensitive (always requires Security check).

        Args:
            operation: Operation name (e.g., "jira_create").

        Returns:
            True if operation is in SENSITIVE_OPS list.
        """
        from src.personas.config import SENSITIVE_OPS
        return operation in SENSITIVE_OPS
