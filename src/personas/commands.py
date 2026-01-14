"""Persona slash command handler.

Commands:
- /persona [name] — Switch to persona (pm, security, architect)
- /persona lock — Lock current persona for thread
- /persona unlock — Allow persona switching again
- /persona auto — Enable auto-detection
- /persona off — Disable persona features
- /persona status — Show current persona, lock state, active validators
- /persona list — Show available personas
"""
import logging
from dataclasses import dataclass
from typing import Any, Optional

from src.personas.types import PersonaName, PersonaReason
from src.personas.config import PERSONAS, get_persona, PERSONA_VALIDATORS
from src.personas.switcher import PersonaSwitcher, SwitchResult

logger = logging.getLogger(__name__)


@dataclass
class CommandResult:
    """Result of persona command execution."""
    success: bool
    message: str
    state_update: Optional[dict[str, Any]] = None
    blocks: Optional[list[dict]] = None  # Slack blocks for rich response


class PersonaCommandHandler:
    """Handles /persona slash commands."""

    def __init__(self) -> None:
        self._switcher = PersonaSwitcher()

    def parse_command(self, text: str) -> tuple[str, Optional[str]]:
        """Parse command text into action and argument.

        Examples:
            "security" -> ("switch", "security")
            "lock" -> ("lock", None)
            "status" -> ("status", None)
            "" -> ("status", None)  # default
        """
        parts = text.strip().lower().split(maxsplit=1)

        if not parts or not parts[0]:
            return ("status", None)

        action = parts[0]
        arg = parts[1] if len(parts) > 1 else None

        # Check if action is actually a persona name (shortcut)
        if action in [p.value for p in PersonaName]:
            return ("switch", action)

        return (action, arg)

    def execute(
        self,
        action: str,
        arg: Optional[str],
        state: dict[str, Any],
    ) -> CommandResult:
        """Execute a persona command.

        Args:
            action: Command action (switch, lock, unlock, status, list, auto, off).
            arg: Optional argument (persona name for switch).
            state: Current AgentState dict.

        Returns:
            CommandResult with response and optional state update.
        """
        handlers = {
            "switch": self._handle_switch,
            "lock": self._handle_lock,
            "unlock": self._handle_unlock,
            "status": self._handle_status,
            "list": self._handle_list,
            "auto": self._handle_auto,
            "off": self._handle_off,
        }

        handler = handlers.get(action, self._handle_unknown)
        return handler(arg, state)

    def _handle_switch(
        self,
        persona_name: Optional[str],
        state: dict[str, Any],
    ) -> CommandResult:
        """Switch to specified persona."""
        if not persona_name:
            return CommandResult(
                success=False,
                message="Usage: /persona [pm|security|architect]",
            )

        # Validate persona name
        try:
            target = PersonaName(persona_name.lower())
        except ValueError:
            return CommandResult(
                success=False,
                message=f"Unknown persona: {persona_name}. Use: pm, security, architect",
            )

        current = PersonaName(state.get("persona", "pm"))

        # Use switcher for consistent behavior
        switch_result = self._switcher.evaluate_switch(
            message="",  # No message needed for explicit switch
            current_persona=current,
            is_locked=state.get("persona_lock", False),
            force_persona=target,
        )

        if not switch_result.switched:
            return CommandResult(
                success=True,
                message=switch_result.message,
            )

        state_update = self._switcher.apply_switch(state, switch_result)
        persona_config = get_persona(target)

        return CommandResult(
            success=True,
            message=f"{persona_config.emoji} Switched to *{persona_config.display_name}* mode",
            state_update=state_update,
        )

    def _handle_lock(
        self,
        _arg: Optional[str],
        state: dict[str, Any],
    ) -> CommandResult:
        """Lock current persona for thread."""
        if state.get("persona_lock", False):
            return CommandResult(
                success=True,
                message="Persona already locked for this thread",
            )

        state_update = self._switcher.lock(state)
        current = PersonaName(state.get("persona", "pm"))
        persona_config = get_persona(current)

        return CommandResult(
            success=True,
            message=f"Locked {persona_config.emoji} {persona_config.display_name} for this thread",
            state_update=state_update,
        )

    def _handle_unlock(
        self,
        _arg: Optional[str],
        state: dict[str, Any],
    ) -> CommandResult:
        """Unlock persona (allow re-detection)."""
        if not state.get("persona_lock", False):
            return CommandResult(
                success=True,
                message="Persona already unlocked",
            )

        state_update = self._switcher.unlock(state)

        return CommandResult(
            success=True,
            message="Persona unlocked - auto-detection enabled",
            state_update=state_update,
        )

    def _handle_status(
        self,
        _arg: Optional[str],
        state: dict[str, Any],
    ) -> CommandResult:
        """Show current persona status."""
        current = PersonaName(state.get("persona", "pm"))
        persona_config = get_persona(current)
        is_locked = state.get("persona_lock", False)
        reason = state.get("persona_reason", "default")
        confidence = state.get("persona_confidence")

        validators = PERSONA_VALIDATORS.get(current, ())

        status_lines = [
            f"{persona_config.emoji} *Current Persona:* {persona_config.display_name}",
            f"*Lock Status:* {'Locked' if is_locked else 'Unlocked'}",
            f"*Reason:* {reason}" + (f" (confidence: {confidence:.0%})" if confidence else ""),
            f"*Active Validators:* {', '.join(validators) if validators else 'none'}",
        ]

        return CommandResult(
            success=True,
            message="\n".join(status_lines),
        )

    def _handle_list(
        self,
        _arg: Optional[str],
        state: dict[str, Any],
    ) -> CommandResult:
        """List available personas."""
        lines = ["*Available Personas:*"]

        for name, config in PERSONAS.items():
            validators = ", ".join(PERSONA_VALIDATORS.get(name, ()))
            lines.append(
                f"{config.emoji} *{config.display_name}* (`{name.value}`) - {config.risk_tolerance.value} risk, checks: {validators}"
            )

        return CommandResult(
            success=True,
            message="\n".join(lines),
        )

    def _handle_auto(
        self,
        _arg: Optional[str],
        state: dict[str, Any],
    ) -> CommandResult:
        """Enable auto-detection (same as unlock)."""
        return self._handle_unlock(_arg, state)

    def _handle_off(
        self,
        _arg: Optional[str],
        state: dict[str, Any],
    ) -> CommandResult:
        """Disable persona features (lock as PM)."""
        state_update = {
            "persona": PersonaName.PM.value,
            "persona_lock": True,
            "persona_reason": PersonaReason.EXPLICIT.value,
        }

        return CommandResult(
            success=True,
            message="Persona features disabled - locked as PM",
            state_update=state_update,
        )

    def _handle_unknown(
        self,
        action: Optional[str],
        state: dict[str, Any],
    ) -> CommandResult:
        """Handle unknown command."""
        return CommandResult(
            success=False,
            message=f"Unknown command: {action}\n\nUsage:\n- /persona [pm|security|architect]\n- /persona lock|unlock|status|list",
        )


# Convenience function
def handle_persona_command(
    text: str,
    state: dict[str, Any],
) -> CommandResult:
    """Handle /persona slash command.

    Args:
        text: Command text (after "/persona ").
        state: Current AgentState dict.

    Returns:
        CommandResult with response.
    """
    handler = PersonaCommandHandler()
    action, arg = handler.parse_command(text)
    return handler.execute(action, arg, state)
