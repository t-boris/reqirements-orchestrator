"""Impact analysis node."""

import structlog
from langchain_core.prompts import ChatPromptTemplate

from src.graph.state import (
    HumanDecision,
    IntentType,
    RequirementState,
    WorkflowPhase,
)

from src.graph.nodes.common import (
    parse_llm_json_response,
    get_llm_for_state,
    logger,
)

# =============================================================================
# Impact Analysis Node
# =============================================================================

IMPACT_ANALYSIS_PROMPT = """You are analyzing the impact of a change request on existing requirements.

## Current State
Epics: {epics}
Stories: {stories}
Tasks: {tasks}
Architecture: {architecture}

## Change Request
{change_request}

## Impact Categories
Classify the impact and determine what needs to be re-evaluated:

1. **architecture**: Changes to system design, components, integrations, or technical approach
   - Examples: "switch to microservices", "add Redis caching", "change database"
   - Requires: Re-evaluate architecture → scope → stories → tasks → estimation

2. **scope**: Changes to what's included/excluded, epic-level changes
   - Examples: "add mobile app support", "remove admin panel", "add new epic"
   - Requires: Re-evaluate scope → stories → tasks → estimation

3. **story**: Changes to user stories, acceptance criteria, priorities
   - Examples: "add new story", "change acceptance criteria", "reprioritize"
   - Requires: Re-evaluate stories → tasks → estimation

4. **task**: Changes to technical tasks, dependencies
   - Examples: "add new task", "change task order", "update dependencies"
   - Requires: Re-evaluate tasks → estimation

5. **estimation**: Changes to estimates only
   - Examples: "increase story points", "add buffer time"
   - Requires: Re-evaluate estimation only

6. **text_only**: Minor text changes that don't affect structure
   - Examples: "fix typo", "clarify description", "update wording"
   - Requires: Direct update, no re-evaluation

Respond in JSON:
{{
    "impact_level": "<architecture|scope|story|task|estimation|text_only>",
    "confidence": <0.0-1.0>,
    "affected_items": ["<item key or index>", ...],
    "reasoning": "<brief explanation>",
    "cascade_phases": ["<phase1>", "<phase2>", ...],
    "suggested_action": "<what to do next>"
}}
"""


class ImpactLevel:
    """Impact levels for change classification."""
    ARCHITECTURE = "architecture"
    SCOPE = "scope"
    STORY = "story"
    TASK = "task"
    ESTIMATION = "estimation"
    TEXT_ONLY = "text_only"


# Mapping from impact level to starting phase
IMPACT_TO_PHASE = {
    ImpactLevel.ARCHITECTURE: WorkflowPhase.ARCHITECTURE.value,
    ImpactLevel.SCOPE: WorkflowPhase.SCOPE.value,
    ImpactLevel.STORY: WorkflowPhase.STORIES.value,
    ImpactLevel.TASK: WorkflowPhase.TASKS.value,
    ImpactLevel.ESTIMATION: WorkflowPhase.ESTIMATION.value,
    ImpactLevel.TEXT_ONLY: None,  # Direct update, no phase
}


async def impact_analysis_node(state: RequirementState) -> dict:
    """
    Analyze the impact of a change request and determine re-evaluation path.

    Used when user wants to modify existing requirements after they've been
    through the full workflow. Determines which phases need to be re-run.
    """
    message = state.get("message", "")

    # Get current state summary
    epics = state.get("epics", [])
    stories = state.get("stories", [])
    tasks = state.get("tasks", [])
    architecture = state.get("chosen_architecture", {})

    logger.info(
        "impact_analysis_started",
        channel_id=state.get("channel_id"),
        epic_count=len(epics),
        story_count=len(stories),
        task_count=len(tasks),
    )

    # Format current state for LLM
    epics_summary = "\n".join(
        f"- Epic {i}: {e.get('title', 'Untitled')}"
        for i, e in enumerate(epics)
    ) or "None defined"

    stories_summary = "\n".join(
        f"- Story {i} (Epic {s.get('epic_index', 0)}): {s.get('title', 'Untitled')}"
        for i, s in enumerate(stories)
    ) or "None defined"

    tasks_summary = "\n".join(
        f"- Task {i} (Story {t.get('story_index', 0)}): {t.get('title', 'Untitled')}"
        for i, t in enumerate(tasks)
    ) or "None defined"

    arch_summary = architecture.get("name", "Not chosen") if architecture else "Not chosen"

    llm = get_llm_for_state(state, temperature=0.2)

    prompt = ChatPromptTemplate.from_template(IMPACT_ANALYSIS_PROMPT)
    messages = prompt.format_messages(
        epics=epics_summary,
        stories=stories_summary,
        tasks=tasks_summary,
        architecture=arch_summary,
        change_request=message,
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        impact_level = result.get("impact_level", ImpactLevel.TEXT_ONLY)
        confidence = result.get("confidence", 0.5)
        affected_items = result.get("affected_items", [])
        reasoning = result.get("reasoning", "")
        cascade_phases = result.get("cascade_phases", [])
        suggested_action = result.get("suggested_action", "")

        logger.info(
            "impact_analysis_complete",
            impact_level=impact_level,
            confidence=confidence,
            affected_count=len(affected_items),
        )

        # Determine restart phase
        restart_phase = IMPACT_TO_PHASE.get(impact_level)

        # Build response for user
        impact_emoji = {
            ImpactLevel.ARCHITECTURE: "🏗️",
            ImpactLevel.SCOPE: "📦",
            ImpactLevel.STORY: "📝",
            ImpactLevel.TASK: "🔧",
            ImpactLevel.ESTIMATION: "📊",
            ImpactLevel.TEXT_ONLY: "✏️",
        }

        response_lines = [
            f"{impact_emoji.get(impact_level, '📋')} *Impact Analysis*",
            f"",
            f"*Level:* {impact_level.replace('_', ' ').title()}",
            f"*Reason:* {reasoning}",
        ]

        if affected_items:
            response_lines.append(f"*Affected:* {', '.join(str(i) for i in affected_items)}")

        if cascade_phases:
            response_lines.append(f"*Phases to re-run:* {' → '.join(cascade_phases)}")

        if suggested_action:
            response_lines.append(f"\n_{suggested_action}_")

        return {
            "impact_level": impact_level,
            "impact_confidence": confidence,
            "affected_items": affected_items,
            "cascade_phases": cascade_phases,
            "restart_phase": restart_phase,
            "response": "\n".join(response_lines),
            "should_respond": True,
        }

    except Exception as e:
        logger.error("impact_analysis_failed", error=str(e))
        return {
            "impact_level": ImpactLevel.TEXT_ONLY,
            "response": f"Could not analyze impact: {str(e)}. Treating as minor change.",
            "error": str(e),
        }

