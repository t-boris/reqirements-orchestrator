"""
Progress Indication System - Real-time workflow progress in Slack.

Provides visual feedback to users as the bot processes multi-phase requirements.
Uses Slack message editing to update progress in place.
"""

from typing import Any

import structlog

from src.graph.state import WorkflowPhase, ProgressStepStatus

logger = structlog.get_logger()


# Default progress steps for full workflow
DEFAULT_PROGRESS_STEPS = [
    {"name": "Analyzing request", "phase": WorkflowPhase.INTAKE.value},
    {"name": "Discovery & clarification", "phase": WorkflowPhase.DISCOVERY.value},
    {"name": "Architecture options", "phase": WorkflowPhase.ARCHITECTURE.value},
    {"name": "Scope definition", "phase": WorkflowPhase.SCOPE.value},
    {"name": "Story breakdown", "phase": WorkflowPhase.STORIES.value},
    {"name": "Task breakdown", "phase": WorkflowPhase.TASKS.value},
    {"name": "Estimation", "phase": WorkflowPhase.ESTIMATION.value},
    {"name": "Security review", "phase": WorkflowPhase.SECURITY.value},
    {"name": "Validation", "phase": WorkflowPhase.VALIDATION.value},
    {"name": "Ready for approval", "phase": WorkflowPhase.REVIEW.value},
]


def get_status_emoji(status: str) -> str:
    """Get emoji for progress step status."""
    status_map = {
        ProgressStepStatus.PENDING.value: "☐",
        ProgressStepStatus.IN_PROGRESS.value: "🔄",
        ProgressStepStatus.COMPLETE.value: "✅",
        ProgressStepStatus.SKIPPED.value: "⏭️",
        ProgressStepStatus.WAITING_USER.value: "⏸️",
    }
    return status_map.get(status, "☐")


def create_initial_progress_steps() -> list[dict[str, Any]]:
    """
    Create the initial list of progress steps with pending status.

    Returns:
        List of progress step dicts with name, phase, and status.
    """
    return [
        {
            "name": step["name"],
            "phase": step["phase"],
            "status": ProgressStepStatus.PENDING.value,
            "detail": None,
        }
        for step in DEFAULT_PROGRESS_STEPS
    ]


def build_progress_blocks(
    steps: list[dict[str, Any]],
    current_detail: str | None = None,
    title: str = "Processing your request...",
) -> list[dict]:
    """
    Build Slack Block Kit blocks for progress display.

    Args:
        steps: List of progress steps with status.
        current_detail: Optional detail text for current operation.
        title: Header text.

    Returns:
        List of Slack blocks.
    """
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"🔄 *{title}*",
            },
        },
        {"type": "divider"},
    ]

    # Build progress list
    progress_lines = []
    for step in steps:
        emoji = get_status_emoji(step.get("status", ProgressStepStatus.PENDING.value))
        name = step.get("name", "Unknown step")
        detail = step.get("detail")

        line = f"{emoji} {name}"
        if detail and step.get("status") == ProgressStepStatus.IN_PROGRESS.value:
            line += f"\n    ↳ _{detail}_"

        progress_lines.append(line)

    # Slack has a 3000 char limit per text block, so split if needed
    progress_text = "\n".join(progress_lines)

    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": f"```\n{progress_text}\n```",
        },
    })

    # Add current operation detail if provided
    if current_detail:
        blocks.append({
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"*Current:* {current_detail}",
                },
            ],
        })

    return blocks


def update_step_status(
    steps: list[dict[str, Any]],
    phase: str,
    status: str,
    detail: str | None = None,
) -> list[dict[str, Any]]:
    """
    Update the status of a specific phase in the steps list.

    Args:
        steps: Current list of progress steps.
        phase: Phase to update (WorkflowPhase value).
        status: New status (ProgressStepStatus value).
        detail: Optional detail text.

    Returns:
        Updated steps list.
    """
    updated_steps = []
    for step in steps:
        step_copy = step.copy()
        if step_copy.get("phase") == phase:
            step_copy["status"] = status
            if detail:
                step_copy["detail"] = detail
        updated_steps.append(step_copy)

    return updated_steps


def mark_phase_complete(
    steps: list[dict[str, Any]],
    phase: str,
) -> list[dict[str, Any]]:
    """Mark a phase as complete."""
    return update_step_status(steps, phase, ProgressStepStatus.COMPLETE.value)


def mark_phase_in_progress(
    steps: list[dict[str, Any]],
    phase: str,
    detail: str | None = None,
) -> list[dict[str, Any]]:
    """Mark a phase as in progress."""
    return update_step_status(steps, phase, ProgressStepStatus.IN_PROGRESS.value, detail)


def mark_phase_waiting(
    steps: list[dict[str, Any]],
    phase: str,
    detail: str | None = None,
) -> list[dict[str, Any]]:
    """Mark a phase as waiting for user input."""
    return update_step_status(steps, phase, ProgressStepStatus.WAITING_USER.value, detail)


def mark_phase_skipped(
    steps: list[dict[str, Any]],
    phase: str,
) -> list[dict[str, Any]]:
    """Mark a phase as skipped."""
    return update_step_status(steps, phase, ProgressStepStatus.SKIPPED.value)


class ProgressReporter:
    """
    Manages progress indication for a workflow execution.

    Handles sending initial progress message and updating it as phases complete.
    """

    def __init__(self, client, channel_id: str, thread_ts: str | None = None):
        """
        Initialize the progress reporter.

        Args:
            client: Slack client for API calls.
            channel_id: Channel to send progress to.
            thread_ts: Thread timestamp (for replies).
        """
        self.client = client
        self.channel_id = channel_id
        self.thread_ts = thread_ts
        self.message_ts: str | None = None
        self.steps: list[dict[str, Any]] = []

    async def start(self, title: str = "Processing your request...") -> str:
        """
        Send the initial progress message.

        Args:
            title: Title for the progress message.

        Returns:
            Message timestamp (for later updates).
        """
        self.steps = create_initial_progress_steps()
        blocks = build_progress_blocks(self.steps, title=title)

        response = await self.client.chat_postMessage(
            channel=self.channel_id,
            thread_ts=self.thread_ts,
            text="Processing your request...",
            blocks=blocks,
        )

        self.message_ts = response.get("ts")

        logger.info(
            "progress_started",
            channel_id=self.channel_id,
            message_ts=self.message_ts,
        )

        return self.message_ts

    async def update_phase(
        self,
        phase: str,
        status: str,
        detail: str | None = None,
        title: str = "Processing your request...",
    ) -> None:
        """
        Update a phase status and refresh the Slack message.

        Args:
            phase: Phase to update (WorkflowPhase value).
            status: New status (ProgressStepStatus value).
            detail: Optional detail text.
            title: Progress message title.
        """
        if not self.message_ts:
            logger.warning("progress_update_without_message", phase=phase)
            return

        self.steps = update_step_status(self.steps, phase, status, detail)
        blocks = build_progress_blocks(self.steps, current_detail=detail, title=title)

        try:
            await self.client.chat_update(
                channel=self.channel_id,
                ts=self.message_ts,
                text="Processing your request...",
                blocks=blocks,
            )

            logger.debug(
                "progress_updated",
                phase=phase,
                status=status,
            )
        except Exception as e:
            logger.error("progress_update_failed", error=str(e), phase=phase)

    async def start_phase(self, phase: str, detail: str | None = None) -> None:
        """Convenience method to mark a phase as in progress."""
        await self.update_phase(phase, ProgressStepStatus.IN_PROGRESS.value, detail)

    async def complete_phase(self, phase: str) -> None:
        """Convenience method to mark a phase as complete."""
        await self.update_phase(phase, ProgressStepStatus.COMPLETE.value)

    async def skip_phase(self, phase: str) -> None:
        """Convenience method to mark a phase as skipped."""
        await self.update_phase(phase, ProgressStepStatus.SKIPPED.value)

    async def wait_for_user(self, phase: str, detail: str | None = None) -> None:
        """Convenience method to mark a phase as waiting for user."""
        await self.update_phase(phase, ProgressStepStatus.WAITING_USER.value, detail)

    async def finish(self, success: bool = True, message: str | None = None) -> None:
        """
        Finish progress tracking with a final status.

        Args:
            success: Whether the workflow completed successfully.
            message: Optional final message.
        """
        if not self.message_ts:
            return

        if success:
            final_text = message or "✅ *Processing complete!*"
        else:
            final_text = message or "❌ *Processing failed*"

        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": final_text,
                },
            },
        ]

        try:
            await self.client.chat_update(
                channel=self.channel_id,
                ts=self.message_ts,
                text=final_text,
                blocks=blocks,
            )

            logger.info(
                "progress_finished",
                success=success,
                channel_id=self.channel_id,
            )
        except Exception as e:
            logger.error("progress_finish_failed", error=str(e))

    def get_state_updates(self) -> dict[str, Any]:
        """
        Get state updates to persist progress.

        Returns:
            Dict with progress_message_ts and progress_steps.
        """
        return {
            "progress_message_ts": self.message_ts,
            "progress_steps": self.steps,
        }

    @classmethod
    def from_state(
        cls,
        client,
        channel_id: str,
        thread_ts: str | None,
        progress_message_ts: str | None,
        progress_steps: list[dict[str, Any]] | None,
    ) -> "ProgressReporter":
        """
        Restore a ProgressReporter from saved state.

        Args:
            client: Slack client.
            channel_id: Channel ID.
            thread_ts: Thread timestamp.
            progress_message_ts: Saved message timestamp.
            progress_steps: Saved progress steps.

        Returns:
            Restored ProgressReporter instance.
        """
        reporter = cls(client, channel_id, thread_ts)
        reporter.message_ts = progress_message_ts
        reporter.steps = progress_steps or create_initial_progress_steps()
        return reporter
