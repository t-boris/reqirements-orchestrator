"""Status Card blocks for TaskPlan visualization.

Phase 35: Multi-Intent Task Orchestration

Displays TaskPlan progress as a single editable message:
- Plan header with status and task count
- Task list with status indicators
- Control buttons (Cancel plan, Pause)
- Task-specific buttons (Approve, Reject for blocked tasks)

UI follows from 35-CONTEXT.md vision:
```
MARO Plan #P-184 - BUILD (3 tasks)

1) OPERATE: Jira duplicate check
2) BUILD: Generate stories (3/12)
3) DECIDE: Create in Jira (waiting approval)

Controls:
[Cancel plan]   [Pause]
(3) [Approve] [Reject]
```
"""

from typing import Optional

from src.schemas.task_plan import TaskPlan, Task, TaskStatus, TaskPlanStatus


# Status emoji mapping
TASK_STATUS_EMOJI = {
    TaskStatus.PENDING: ":hourglass_flowing_sand:",  # Waiting
    TaskStatus.RUNNING: ":arrows_counterclockwise:",  # Spinning
    TaskStatus.BLOCKED: ":double_vertical_bar:",     # Paused (needs input)
    TaskStatus.DONE: ":white_check_mark:",           # Complete
    TaskStatus.CANCELED: ":x:",                      # Canceled
}

PLAN_STATUS_EMOJI = {
    TaskPlanStatus.PENDING: ":clipboard:",
    TaskPlanStatus.RUNNING: ":hammer_and_wrench:",
    TaskPlanStatus.BLOCKED: ":double_vertical_bar:",
    TaskPlanStatus.DONE: ":white_check_mark:",
    TaskPlanStatus.CANCELED: ":x:",
}


def build_task_plan_blocks(task_plan: TaskPlan) -> list[dict]:
    """Build Slack blocks for TaskPlan status card.

    Args:
        task_plan: The TaskPlan to visualize

    Returns:
        List of Slack Block Kit blocks
    """
    blocks = []

    # Header with plan status
    plan_emoji = PLAN_STATUS_EMOJI.get(task_plan.status, ":clipboard:")
    mode = task_plan.tasks[0].mode.label if task_plan.tasks else "Processing"
    task_count = len(task_plan.tasks)
    done_count = sum(1 for t in task_plan.tasks if t.status == TaskStatus.DONE)

    header_text = (
        f"{plan_emoji} *MARO Plan* - {mode} ({done_count}/{task_count} tasks)"
    )
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": header_text},
    })

    blocks.append({"type": "divider"})

    # Task list
    task_lines = []
    for idx, task in enumerate(task_plan.tasks, 1):
        emoji = TASK_STATUS_EMOJI.get(task.status, ":question:")
        mode_label = task.mode.value.upper()
        title = task.title

        # Add progress if available
        progress = ""
        if task.progress:
            progress = f" ({task.progress.get('current', 0)}/{task.progress.get('total', 0)})"

        # Add status suffix
        suffix = ""
        if task.status == TaskStatus.BLOCKED and task.requires_user_input:
            suffix = " _(waiting for approval)_"
        elif task.status == TaskStatus.BLOCKED and task.last_error:
            error_preview = task.last_error[:30]
            suffix = f" _(error: {error_preview}...)_"

        task_lines.append(f"{idx}) {emoji} *{mode_label}*: {title}{progress}{suffix}")

    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": "\n".join(task_lines)},
    })

    # Control buttons
    control_elements = []

    # Cancel plan button (always available if not done)
    if task_plan.status not in (TaskPlanStatus.DONE, TaskPlanStatus.CANCELED):
        control_elements.append({
            "type": "button",
            "text": {"type": "plain_text", "text": "Cancel plan"},
            "style": "danger",
            "action_id": "task_plan_cancel",
            "value": f"{task_plan.plan_id}:{task_plan.version}",
        })

    # Add task-specific buttons for blocked tasks
    for idx, task in enumerate(task_plan.tasks, 1):
        if task.status == TaskStatus.BLOCKED and task.requires_user_input:
            control_elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": f"({idx}) Approve"},
                "style": "primary",
                "action_id": "task_approve",
                "value": f"{task_plan.plan_id}:{task.task_id}:{task_plan.version}",
            })
            control_elements.append({
                "type": "button",
                "text": {"type": "plain_text", "text": f"({idx}) Reject"},
                "action_id": "task_reject",
                "value": f"{task_plan.plan_id}:{task.task_id}:{task_plan.version}",
            })

    if control_elements:
        blocks.append({
            "type": "actions",
            "elements": control_elements[:5],  # Slack limit: 5 buttons per actions block
        })

        # If more buttons, add another actions block
        if len(control_elements) > 5:
            blocks.append({
                "type": "actions",
                "elements": control_elements[5:10],
            })

    # Footer with version for debugging
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"Plan v{task_plan.version}"},
        ],
    })

    return blocks


def build_plan_complete_message(task_plan: TaskPlan) -> str:
    """Build completion message for channel announcement.

    Short, commit-like summary posted to channel when plan completes.
    """
    done_tasks = [t for t in task_plan.tasks if t.status == TaskStatus.DONE]
    if not done_tasks:
        return "Plan completed with no tasks executed."

    summaries = [f"* {t.title}" for t in done_tasks[:3]]
    if len(done_tasks) > 3:
        summaries.append(f"* ... and {len(done_tasks) - 3} more")

    return f":white_check_mark: Completed {len(done_tasks)} tasks:\n" + "\n".join(summaries)


def build_plan_canceled_message(task_plan: TaskPlan, user_id: str) -> str:
    """Build cancellation message."""
    return f":x: Plan canceled by <@{user_id}>"


def build_multi_intent_announcement(task_plan: TaskPlan) -> str:
    """Build the canonical multi-intent announcement.

    From 35-CONTEXT.md:
    ```
    Got it. I see 3 actions:
    1. Create list of Epics from Decisions
    2. Check duplicates in Jira
    3. Provide architecture recommendations

    Executing 1 and 2 now. For 3 - OK?
    ```
    """
    if not task_plan.tasks:
        return "No tasks identified."

    # Build task list
    task_word = "action" if len(task_plan.tasks) == 1 else "actions"
    lines = [f"Got it. I see {len(task_plan.tasks)} {task_word}:"]
    for idx, task in enumerate(task_plan.tasks, 1):
        lines.append(f"{idx}. {task.title}")

    lines.append("")

    # Identify auto-executable vs confirmation-required
    auto_tasks = [t for t in task_plan.tasks if t.can_auto_execute()]
    confirm_tasks = [t for t in task_plan.tasks if t.needs_confirmation()]

    if auto_tasks and confirm_tasks:
        auto_indices = [str(task_plan.tasks.index(t) + 1) for t in auto_tasks]
        confirm_indices = [str(task_plan.tasks.index(t) + 1) for t in confirm_tasks]

        if len(auto_tasks) == 1:
            lines.append(f"Executing {auto_indices[0]} now.")
        else:
            lines.append(f"Executing {', '.join(auto_indices[:-1])} and {auto_indices[-1]} now.")

        if len(confirm_tasks) == 1:
            lines.append(f"For {confirm_indices[0]} - OK?")
        else:
            lines.append(f"For {', '.join(confirm_indices)} - OK?")

    elif auto_tasks:
        lines.append("Executing all tasks now.")
    elif confirm_tasks:
        lines.append("All tasks require approval. Ready when you are.")

    return "\n".join(lines)


def build_task_summary_line(task: Task, include_status: bool = True) -> str:
    """Build a single-line summary for a task.

    For channel announcements after completion.
    """
    if include_status:
        emoji = TASK_STATUS_EMOJI.get(task.status, ":question:")
        return f"{emoji} {task.title}"
    return task.title
