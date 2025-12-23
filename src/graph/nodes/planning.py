"""Planning nodes: scope, stories, tasks."""

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
    determine_response_target,
    logger,
    settings,
)

# =============================================================================
# Scope Definition Node (Phase 4)
# =============================================================================

SCOPE_PROMPT = """You are a product strategist defining project scope.
{persona_knowledge}

## Context
Goal: {goal}
Chosen Architecture: {architecture}
Discovered Requirements:
{requirements}

## Your Task
Define the project scope clearly:
1. Create Epic(s) - high-level initiative containers
2. Define what's IN scope for MVP
3. Define what's OUT of scope (future phases)
4. Set clear boundaries

## Guidelines
- Be specific about what's included
- Group related functionality
- Prioritize ruthlessly for MVP
- Consider dependencies

Respond in JSON format:
{{
    "epics": [
        {{
            "title": "<epic title>",
            "description": "<2-3 sentence description>",
            "objective": "<what success looks like>",
            "priority": "<critical|high|medium|low>"
        }}
    ],
    "in_scope": [
        "<specific feature or capability 1>",
        "<specific feature or capability 2>"
    ],
    "out_of_scope": [
        "<feature for future phase 1>",
        "<feature for future phase 2>"
    ],
    "assumptions": ["<assumption 1>", ...],
    "dependencies": ["<external dependency 1>", ...],
    "risks": ["<risk 1>", ...]
}}
"""


async def scope_definition_node(state: RequirementState) -> dict:
    """
    Define project scope based on chosen architecture.

    This node:
    1. Creates Epic definition(s)
    2. Defines in-scope vs out-of-scope items
    3. Identifies assumptions, dependencies, risks

    This is Phase 4 of the multi-phase workflow.
    """
    logger.info(
        "scope_definition",
        channel_id=state.get("channel_id"),
        chosen_architecture=state.get("chosen_architecture"),
    )

    llm = get_llm_for_state(state, temperature=0.3)

    # Use product_manager persona for scope
    persona_knowledge = get_persona_knowledge("product_manager", state)

    # Build requirements summary
    requirements = state.get("discovered_requirements", [])
    req_str = "\n".join(
        f"- [{r.get('type')}] {r.get('description')}"
        for r in requirements
    ) if requirements else "No specific requirements."

    # Get chosen architecture
    chosen = state.get("chosen_architecture")
    arch_options = state.get("architecture_options", [])
    arch_str = "Not yet selected"
    if chosen:
        for opt in arch_options:
            if opt.get("name") == chosen:
                arch_str = f"{opt.get('name')}: {opt.get('description')}"
                break

    prompt = ChatPromptTemplate.from_template(SCOPE_PROMPT)
    messages = prompt.format_messages(
        goal=state.get("current_goal") or "Not yet established",
        architecture=arch_str,
        requirements=req_str,
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        epics = result.get("epics", [])
        in_scope = result.get("in_scope", [])
        out_of_scope = result.get("out_of_scope", [])

        logger.info(
            "scope_defined",
            epic_count=len(epics),
            in_scope_count=len(in_scope),
            out_of_scope_count=len(out_of_scope),
        )

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.SCOPE.value not in phase_history:
            phase_history.append(WorkflowPhase.SCOPE.value)

        # Format response for user confirmation
        response_text = _format_scope(epics, in_scope, out_of_scope)
        response_text += "\n\nDoes this scope look correct? Reply 'yes' to proceed, or suggest changes."

        return {
            "current_phase": WorkflowPhase.SCOPE.value,
            "phase_history": phase_history,
            "epics": epics,
            "response": response_text,
            "should_respond": True,
            "response_target": determine_response_target(state, new_phase="scope"),
        }

    except Exception as e:
        logger.error("scope_definition_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.SCOPE.value,
            "error": f"Scope definition failed: {str(e)}",
        }


def _format_scope(
    epics: list[dict],
    in_scope: list[str],
    out_of_scope: list[str],
) -> str:
    """Format scope definition for Slack display."""
    lines = ["*Scope Definition*\n"]

    # Epics
    for epic in epics:
        lines.append(f"\n*Epic: {epic.get('title', 'Untitled')}*")
        lines.append(f"_{epic.get('description', '')}_")
        lines.append(f"Priority: {epic.get('priority', 'medium')}")

    # In Scope
    lines.append("\n*In Scope (MVP):*")
    for item in in_scope:
        lines.append(f"✅ {item}")

    # Out of Scope
    if out_of_scope:
        lines.append("\n*Out of Scope (Future):*")
        for item in out_of_scope:
            lines.append(f"❌ {item}")

    return "\n".join(lines)


# =============================================================================
# Story Breakdown Node (Phase 5)
# =============================================================================

STORY_BREAKDOWN_PROMPT = """You are a product manager expert at writing user stories.
{persona_knowledge}

## Context
Goal: {goal}
Epics to break down:
{epics}

Chosen Architecture: {architecture}

## Your Task
Break each Epic into well-formed user stories:
1. Use proper user story format: "As a [role], I want [goal], so that [benefit]"
2. Define clear acceptance criteria
3. Apply MoSCoW prioritization (Must/Should/Could/Won't)
4. Keep stories small enough for 1-2 sprint completion

## Guidelines
- Each Epic should have 3-7 stories
- Stories should be independently testable
- Include edge cases and error handling stories
- Consider user types and their specific needs

Respond in JSON format:
{{
    "stories": [
        {{
            "epic_index": <0-based index of parent epic>,
            "title": "<story title>",
            "as_a": "<user role>",
            "i_want": "<goal>",
            "so_that": "<benefit>",
            "acceptance_criteria": [
                "<criterion 1>",
                "<criterion 2>"
            ],
            "priority": "<Must|Should|Could|Won't>",
            "labels": ["<label1>", ...]
        }}
    ],
    "total_stories": <count>,
    "coverage_notes": "<any gaps or missing areas>"
}}
"""


async def story_breakdown_node(state: RequirementState) -> dict:
    """
    Break epics into user stories with acceptance criteria.

    This node:
    1. Uses Product Manager persona
    2. Creates user stories for each epic
    3. Applies MoSCoW prioritization
    4. Generates acceptance criteria

    This is Phase 5 of the multi-phase workflow.
    """
    logger.info(
        "story_breakdown",
        channel_id=state.get("channel_id"),
        epic_count=len(state.get("epics", [])),
    )

    llm = get_llm_for_state(state, temperature=0.3)

    # Use product_manager persona
    persona_knowledge = get_persona_knowledge("product_manager", state)

    # Format epics
    epics = state.get("epics", [])
    epics_str = "\n".join(
        f"{i}. {e.get('title', 'Untitled')}: {e.get('description', '')}"
        for i, e in enumerate(epics)
    ) if epics else "No epics defined."

    # Get architecture
    chosen = state.get("chosen_architecture")
    arch_options = state.get("architecture_options", [])
    arch_str = "Not specified"
    if chosen:
        for opt in arch_options:
            if opt.get("name") == chosen:
                arch_str = opt.get("description", chosen)
                break

    prompt = ChatPromptTemplate.from_template(STORY_BREAKDOWN_PROMPT)
    messages = prompt.format_messages(
        goal=state.get("current_goal") or "Not yet established",
        epics=epics_str,
        architecture=arch_str,
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        stories = result.get("stories", [])
        coverage_notes = result.get("coverage_notes", "")

        logger.info(
            "stories_created",
            story_count=len(stories),
        )

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.STORIES.value not in phase_history:
            phase_history.append(WorkflowPhase.STORIES.value)

        # Format response
        response_text = _format_stories(stories, epics)
        if coverage_notes:
            response_text += f"\n\n_Note: {coverage_notes}_"
        response_text += "\n\nDo these stories look good? Reply 'yes' to proceed to task breakdown, or suggest changes."

        return {
            "current_phase": WorkflowPhase.STORIES.value,
            "phase_history": phase_history,
            "stories": stories,
            "response": response_text,
            "should_respond": True,
            "response_target": determine_response_target(state, new_phase="stories"),
        }

    except Exception as e:
        logger.error("story_breakdown_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.STORIES.value,
            "error": f"Story breakdown failed: {str(e)}",
        }


def _format_stories(stories: list[dict], epics: list[dict]) -> str:
    """Format stories for Slack display."""
    lines = ["*User Stories*\n"]

    # Group by epic
    epic_stories: dict[int, list[dict]] = {}
    for story in stories:
        epic_idx = story.get("epic_index", 0)
        if epic_idx not in epic_stories:
            epic_stories[epic_idx] = []
        epic_stories[epic_idx].append(story)

    for epic_idx, epic_story_list in sorted(epic_stories.items()):
        epic_title = epics[epic_idx].get("title", f"Epic {epic_idx}") if epic_idx < len(epics) else f"Epic {epic_idx}"
        lines.append(f"\n*{epic_title}*")

        for story in epic_story_list:
            priority_emoji = {
                "Must": "🔴",
                "Should": "🟡",
                "Could": "🟢",
                "Won't": "⚪",
            }.get(story.get("priority", ""), "⚪")

            lines.append(f"\n{priority_emoji} *{story.get('title', 'Untitled')}*")
            lines.append(f"  As a {story.get('as_a', '...')}, I want {story.get('i_want', '...')}, so that {story.get('so_that', '...')}")

            # Acceptance criteria (first 3)
            ac = story.get("acceptance_criteria", [])[:3]
            if ac:
                lines.append("  Acceptance:")
                for criterion in ac:
                    lines.append(f"    ✓ {criterion}")

    return "\n".join(lines)


# =============================================================================
# Task Breakdown Node (Phase 6)
# =============================================================================

TASK_BREAKDOWN_PROMPT = """You are a technical lead breaking stories into implementation tasks.
{persona_knowledge}

## Context
Goal: {goal}
Architecture: {architecture}
Stories to break down:
{stories}

## Your Task
Break each story into technical tasks:
1. Identify specific implementation steps
2. Map dependencies between tasks
3. Estimate complexity (S/M/L/XL)
4. Suggest implementation order

## Guidelines
- Tasks should be 0.5-2 days of work
- Include setup, testing, and documentation tasks
- Identify critical path dependencies
- Flag any risks or blockers

Respond in JSON format:
{{
    "tasks": [
        {{
            "story_index": <0-based index of parent story>,
            "title": "<task title>",
            "description": "<what needs to be done>",
            "complexity": "<S|M|L|XL>",
            "dependencies": [<indices of dependent tasks>],
            "tags": ["<backend|frontend|database|testing|devops>", ...]
        }}
    ],
    "critical_path": [<task indices in order>],
    "estimated_total_days": <number>,
    "risks": ["<risk 1>", ...]
}}
"""


async def task_breakdown_node(state: RequirementState) -> dict:
    """
    Break stories into technical tasks with dependencies.

    This node:
    1. Uses Architect persona for technical breakdown
    2. Creates tasks for each story
    3. Maps dependencies
    4. Estimates complexity

    This is Phase 6 of the multi-phase workflow.
    """
    logger.info(
        "task_breakdown",
        channel_id=state.get("channel_id"),
        story_count=len(state.get("stories", [])),
    )

    llm = get_llm_for_state(state, temperature=0.3)

    # Use architect persona for technical tasks
    persona_knowledge = get_persona_knowledge("architect", state)

    # Format stories
    stories = state.get("stories", [])
    stories_str = "\n".join(
        f"{i}. [{s.get('priority', 'M')}] {s.get('title', 'Untitled')}: {s.get('i_want', '')}"
        for i, s in enumerate(stories)
    ) if stories else "No stories defined."

    # Get architecture
    chosen = state.get("chosen_architecture")
    arch_options = state.get("architecture_options", [])
    arch_str = "Not specified"
    if chosen:
        for opt in arch_options:
            if opt.get("name") == chosen:
                arch_str = opt.get("description", chosen)
                break

    prompt = ChatPromptTemplate.from_template(TASK_BREAKDOWN_PROMPT)
    messages = prompt.format_messages(
        goal=state.get("current_goal") or "Not yet established",
        stories=stories_str,
        architecture=arch_str,
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        tasks = result.get("tasks", [])
        critical_path = result.get("critical_path", [])
        estimated_days = result.get("estimated_total_days", 0)
        risks = result.get("risks", [])

        logger.info(
            "tasks_created",
            task_count=len(tasks),
            estimated_days=estimated_days,
        )

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.TASKS.value not in phase_history:
            phase_history.append(WorkflowPhase.TASKS.value)

        # Format response
        response_text = _format_tasks(tasks, stories, estimated_days, risks)
        response_text += "\n\nReady for estimation? Reply 'yes' to continue."

        return {
            "current_phase": WorkflowPhase.TASKS.value,
            "phase_history": phase_history,
            "tasks": tasks,
            "response": response_text,
            "should_respond": True,
        }

    except Exception as e:
        logger.error("task_breakdown_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.TASKS.value,
            "error": f"Task breakdown failed: {str(e)}",
        }


def _format_tasks(
    tasks: list[dict],
    stories: list[dict],
    estimated_days: int,
    risks: list[str],
) -> str:
    """Format tasks for Slack display."""
    lines = ["*Technical Tasks*\n"]

    # Group by story
    story_tasks: dict[int, list[dict]] = {}
    for i, task in enumerate(tasks):
        story_idx = task.get("story_index", 0)
        if story_idx not in story_tasks:
            story_tasks[story_idx] = []
        task["_index"] = i
        story_tasks[story_idx].append(task)

    for story_idx, task_list in sorted(story_tasks.items()):
        story_title = stories[story_idx].get("title", f"Story {story_idx}") if story_idx < len(stories) else f"Story {story_idx}"
        lines.append(f"\n*{story_title}*")

        for task in task_list:
            complexity_emoji = {
                "S": "🟢",
                "M": "🟡",
                "L": "🟠",
                "XL": "🔴",
            }.get(task.get("complexity", "M"), "⚪")

            tags = task.get("tags", [])
            tags_str = f" [{', '.join(tags)}]" if tags else ""

            lines.append(f"  {complexity_emoji} {task.get('title', 'Untitled')}{tags_str}")

    # Summary
    lines.append(f"\n*Estimated Total:* ~{estimated_days} days")

    if risks:
        lines.append("\n*Risks:*")
        for risk in risks[:3]:
            lines.append(f"  ⚠️ {risk}")

    return "\n".join(lines)

