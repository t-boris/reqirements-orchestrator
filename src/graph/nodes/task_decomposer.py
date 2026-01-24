"""Task decomposer node for multi-intent orchestration.

Phase 35: Multi-Intent Task Orchestration

Converts TaskPlanProposal (classification output) to TaskPlan (executable plan).
Sets up task dependencies, infers safety levels, persists to database.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from src.db.connection import get_connection
from src.db.task_plan_store import TaskPlanStore
from src.graph.safety import create_task_with_inferred_safety
from src.schemas.intent import TaskPlanProposal
from src.schemas.state import AgentState
from src.schemas.task_plan import TaskPlan, TaskPlanStatus

logger = logging.getLogger(__name__)


async def task_decomposer_node(state: AgentState) -> dict[str, Any]:
    """Convert TaskPlanProposal to persisted TaskPlan.

    Called when multi-intent is detected (is_multi_intent=True).
    Creates TaskPlan with tasks, sets dependencies, persists to DB.

    Flow:
    1. Extract TaskPlanProposal from intent_result
    2. Convert TaskProposal items to Task objects with inferred safety
    3. Resolve dependency indices to task_ids
    4. Create and persist TaskPlan to database
    5. Return task_plan in state for downstream nodes

    Args:
        state: Current AgentState with intent_result containing task_plan_proposal.

    Returns:
        State update with task_plan populated (serialized as dict).
    """
    intent_result = state.get("intent_result", {})
    proposal_data = intent_result.get("task_plan_proposal")

    if not proposal_data:
        logger.warning("task_decomposer called without proposal")
        return {}

    # Reconstruct proposal from dict
    proposal = TaskPlanProposal.model_validate(proposal_data)

    if not proposal.is_multi_intent:
        logger.debug("Single-intent proposal, skipping decomposition")
        return {}

    # Generate unique plan ID
    plan_id = str(uuid.uuid4())

    # Convert TaskProposals to Tasks
    tasks = []
    for tp in proposal.tasks:
        task = create_task_with_inferred_safety(
            task_id=str(uuid.uuid4()),
            intent=tp.intent,
            mode=tp.super_mode,
            title=tp.title,
            params=tp.params,
        )
        tasks.append(task)

    # Resolve dependency indices to task_ids
    # Each TaskProposal has depends_on_indices (list of ints),
    # we convert those to the actual task_ids after all tasks are created
    for idx, task in enumerate(tasks):
        orig_proposal = proposal.tasks[idx]
        if orig_proposal.depends_on_indices:
            task.depends_on = [
                tasks[dep_idx].task_id
                for dep_idx in orig_proposal.depends_on_indices
                if dep_idx < len(tasks)
            ]

    # Create TaskPlan
    now = datetime.now(timezone.utc)
    task_plan = TaskPlan(
        plan_id=plan_id,
        channel_id=state.get("channel_id", ""),
        thread_ts=state.get("thread_ts"),
        anchor=None,  # Will be resolved by first task if needed
        tasks=tasks,
        status=TaskPlanStatus.PENDING,
        created_by=state.get("user_id", ""),
        created_at=now,
        updated_at=now,
    )

    # Persist to database
    async with get_connection() as conn:
        store = TaskPlanStore(conn)
        await store.create(task_plan)

    # Count auto-executable tasks for logging
    auto_executable_count = len([t for t in tasks if t.can_auto_execute()])

    logger.info(
        f"Created TaskPlan {plan_id} with {len(tasks)} tasks "
        f"({auto_executable_count} auto-executable)"
    )

    return {
        "task_plan": task_plan.model_dump(),
    }
