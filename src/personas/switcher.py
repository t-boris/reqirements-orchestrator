"""Persona switching logic with lock/unlock and audit trail.

Rules:
- PM is always default
- Switch only on explicit trigger or high-confidence detection
- Auto-lock once activated (prevents oscillation)
- Every switch is auditable
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from src.personas.types import PersonaName, PersonaReason
from src.personas.config import get_persona, get_default_persona
from src.personas.detector import TopicDetector, DetectionResult

logger = logging.getLogger(__name__)


@dataclass
class SwitchResult:
    """Result of persona switch attempt."""
    switched: bool = False
    persona: PersonaName = PersonaName.PM
    reason: PersonaReason = PersonaReason.DEFAULT
    confidence: Optional[float] = None
    locked: bool = False
    message: str = ""  # Human-readable explanation


class PersonaSwitcher:
    """Manages persona switching with lock/unlock logic.

    Key behaviors:
    - PM is always default
    - Explicit triggers always work (even when locked, but logs warning)
    - Detection-based switches only work when unlocked
    - Auto-lock on any switch (prevents oscillation)
    - Users can /persona unlock to allow re-detection
    """

    def __init__(self) -> None:
        self._detector = TopicDetector()

    def get_initial_state(self) -> dict[str, Any]:
        """Get initial persona state for new thread."""
        return {
            "persona": PersonaName.PM.value,
            "persona_lock": False,
            "persona_reason": PersonaReason.DEFAULT.value,
            "persona_confidence": None,
            "persona_changed_at": datetime.now(timezone.utc).isoformat(),
            "persona_message_count": 0,
        }

    def evaluate_switch(
        self,
        message: str,
        current_persona: PersonaName,
        is_locked: bool,
        force_persona: Optional[PersonaName] = None,
    ) -> SwitchResult:
        """Evaluate whether to switch persona based on message.

        Args:
            message: User message to analyze.
            current_persona: Currently active persona.
            is_locked: Whether persona is locked for thread.
            force_persona: Force switch to specific persona (for /persona command).

        Returns:
            SwitchResult with switch decision.
        """
        result = SwitchResult(persona=current_persona, locked=is_locked)

        # Handle forced persona switch (from /persona command)
        if force_persona:
            if force_persona == current_persona:
                result.message = f"Already in {current_persona.value} mode"
                return result

            result.switched = True
            result.persona = force_persona
            result.reason = PersonaReason.EXPLICIT
            result.locked = True  # Auto-lock on switch
            result.message = f"Switched to {force_persona.value} mode (explicit)"

            logger.info(
                "Persona switch (forced)",
                extra={
                    "from": current_persona.value,
                    "to": force_persona.value,
                    "reason": "explicit_command",
                }
            )
            return result

        # Detect topics in message
        detection = self._detector.detect(message)

        # Handle explicit triggers (@security, @architect)
        if detection.explicit_trigger:
            target = detection.explicit_trigger

            if target == current_persona:
                result.message = f"Already in {current_persona.value} mode"
                return result

            if is_locked and detection.method == "explicit":
                # Explicit triggers work even when locked, but log it
                logger.warning(
                    "Explicit trigger overriding locked persona",
                    extra={
                        "from": current_persona.value,
                        "to": target.value,
                    }
                )

            result.switched = True
            result.persona = target
            result.reason = PersonaReason.EXPLICIT
            result.confidence = 1.0
            result.locked = True  # Auto-lock on switch
            result.message = f"Switched to {target.value} mode (@mention trigger)"

            logger.info(
                "Persona switch (explicit trigger)",
                extra={
                    "from": current_persona.value,
                    "to": target.value,
                    "trigger": detection.reasons[0] if detection.reasons else "explicit",
                }
            )
            return result

        # Handle detection-based switches (only if not locked)
        if is_locked:
            result.message = "Persona locked for this thread"
            return result

        suggested = detection.suggested_persona
        if suggested and suggested != current_persona:
            # Check thresholds
            confidence = (
                detection.security_score if suggested == PersonaName.SECURITY
                else detection.architect_score if suggested == PersonaName.ARCHITECT
                else 0.0
            )

            result.switched = True
            result.persona = suggested
            result.reason = PersonaReason.DETECTED
            result.confidence = confidence
            result.locked = True  # Auto-lock on switch
            result.message = f"Switched to {suggested.value} mode (detected: {', '.join(detection.reasons[:2])})"

            logger.info(
                "Persona switch (detected)",
                extra={
                    "from": current_persona.value,
                    "to": suggested.value,
                    "confidence": confidence,
                    "reasons": detection.reasons[:3],
                }
            )
            return result

        # No switch needed
        return result

    def apply_switch(
        self,
        state: dict[str, Any],
        switch_result: SwitchResult,
    ) -> dict[str, Any]:
        """Apply switch result to state.

        Returns partial state update for AgentState.
        """
        if not switch_result.switched:
            # Just increment message count
            return {
                "persona_message_count": state.get("persona_message_count", 0) + 1,
            }

        return {
            "persona": switch_result.persona.value,
            "persona_lock": switch_result.locked,
            "persona_reason": switch_result.reason.value,
            "persona_confidence": switch_result.confidence,
            "persona_changed_at": datetime.now(timezone.utc).isoformat(),
            "persona_message_count": 0,  # Reset on switch
        }

    def unlock(self, state: dict[str, Any]) -> dict[str, Any]:
        """Unlock persona for thread (allows re-detection).

        Returns partial state update.
        """
        logger.info(
            "Persona unlocked",
            extra={"current_persona": state.get("persona", "pm")}
        )
        return {"persona_lock": False}

    def lock(self, state: dict[str, Any]) -> dict[str, Any]:
        """Lock current persona for thread.

        Returns partial state update.
        """
        logger.info(
            "Persona locked",
            extra={"current_persona": state.get("persona", "pm")}
        )
        return {"persona_lock": True}
