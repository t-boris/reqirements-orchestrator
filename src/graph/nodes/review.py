"""Final review node."""

import structlog
from langchain_core.prompts import ChatPromptTemplate

from src.graph.state import (
    HumanDecision,
    IntentType,
    RequirementState,
    WorkflowPhase,
)

from src.graph.nodes.common import (
    determine_response_target,
    logger,
)

# =============================================================================
# Final Review Node (Phase 10)
# =============================================================================

async def final_review_node(state: RequirementState) -> dict:
    """
    Present final summary for approval before Jira sync.

    This node:
    1. Compiles complete project summary
    2. Shows hierarchy tree (Epic → Stories → Tasks)
    3. Shows estimates and timeline
    4. Prepares for human approval

    This is Phase 10 of the multi-phase workflow.
    """
    logger.info(
        "final_review",
        channel_id=state.get("channel_id"),
        epic_count=len(state.get("epics", [])),
        story_count=len(state.get("stories", [])),
        task_count=len(state.get("tasks", [])),
    )

    # Update phase history
    phase_history = list(state.get("phase_history", []))
    if WorkflowPhase.REVIEW.value not in phase_history:
        phase_history.append(WorkflowPhase.REVIEW.value)

    # Build comprehensive summary
    epics = state.get("epics", [])
    stories = state.get("stories", [])
    tasks = state.get("tasks", [])

    # Format tree view
    response_text = _format_final_summary(
        goal=state.get("current_goal"),
        epics=epics,
        stories=stories,
        tasks=tasks,
        total_points=state.get("total_story_points"),
        total_hours=state.get("total_hours"),
        risk_buffer=state.get("risk_buffer_percent"),
        validation=state.get("validation_report"),
    )

    return {
        "current_phase": WorkflowPhase.REVIEW.value,
        "phase_history": phase_history,
        "response": response_text,
        "should_respond": True,
        "response_target": determine_response_target(state, new_phase="review", is_final_summary=True),
        "awaiting_human": True,  # This will trigger approval buttons
    }


def _format_final_summary(
    goal: str | None,
    epics: list[dict],
    stories: list[dict],
    tasks: list[dict],
    total_points: int | None,
    total_hours: int | None,
    risk_buffer: int | None,
    validation: dict | None,
) -> str:
    """Format final summary for Slack display."""
    lines = ["*📋 Final Requirements Summary*\n"]

    if goal:
        lines.append(f"*Goal:* {goal}\n")

    # Metrics
    lines.append("*Metrics:*")
    lines.append(f"  • Epics: {len(epics)}")
    lines.append(f"  • Stories: {len(stories)}")
    lines.append(f"  • Tasks: {len(tasks)}")
    if total_points:
        lines.append(f"  • Story Points: {total_points} SP")
    if total_hours:
        buffer = risk_buffer or 20
        total_with_buffer = total_hours * (1 + buffer / 100)
        lines.append(f"  • Effort: {total_hours}h (+{buffer}% buffer = {total_with_buffer:.0f}h)")

    # Validation status
    if validation:
        status = "✅" if validation.get("passed") else "⚠️"
        score = validation.get("score", 0)
        lines.append(f"  • Validation: {status} {score}/100")

    # Tree view
    lines.append("\n*Hierarchy:*")
    lines.append("```")

    # Group stories by epic
    for i, epic in enumerate(epics):
        lines.append(f"📦 {epic.get('title', f'Epic {i}')}")

        # Find stories for this epic
        epic_stories = [s for s in stories if s.get("epic_index") == i]
        for j, story in enumerate(epic_stories):
            is_last_story = j == len(epic_stories) - 1
            prefix = "└─" if is_last_story else "├─"
            priority_marker = {"Must": "🔴", "Should": "🟡", "Could": "🟢"}.get(story.get("priority", ""), "")
            lines.append(f"  {prefix} {priority_marker} {story.get('title', 'Story')}")

            # Find original story index to get tasks
            orig_idx = stories.index(story) if story in stories else -1
            story_tasks = [t for t in tasks if t.get("story_index") == orig_idx]
            for k, task in enumerate(story_tasks[:3]):  # Limit tasks shown
                is_last_task = k == len(story_tasks) - 1 or k == 2
                task_prefix = "    └─" if is_last_task else "    ├─"
                complexity = task.get("complexity", "M")
                lines.append(f"  {task_prefix} [{complexity}] {task.get('title', 'Task')}")
            if len(story_tasks) > 3:
                lines.append(f"      ... and {len(story_tasks) - 3} more tasks")

    lines.append("```")

    lines.append("\n*Ready to create in Jira?*")
    lines.append("Use the buttons below to approve, edit, or reject.")

    return "\n".join(lines)

