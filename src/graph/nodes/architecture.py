"""Architecture exploration node."""

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
    get_persona_knowledge,
    determine_response_target,
    logger,
    settings,
)

# =============================================================================
# Architecture Exploration Node (Phase 3)
# =============================================================================

ARCHITECTURE_PROMPT = """You are a senior software architect with deep expertise in system design.
{persona_knowledge}

## Project Context
Goal: {goal}
Discovered Requirements:
{requirements}

User's Original Request:
{user_message}

## Your Task
Analyze the requirements and propose 2-3 architecture options. For each option:
1. Give it a clear name
2. Describe the high-level approach
3. List specific technologies/frameworks
4. Identify pros and cons
5. Provide a rough effort estimate

## Guidelines
- Consider the scale and complexity implied by requirements
- Factor in any mentioned constraints (compliance, performance, timeline)
- Recommend ONE option as best fit with clear reasoning
- Be specific about technologies, not vague
- Consider maintainability and team skills

Respond in JSON format:
{{
    "analysis_summary": "<1-2 sentence summary of what we're building>",
    "key_decisions": ["<decision 1>", "<decision 2>", ...],
    "options": [
        {{
            "name": "<option name>",
            "recommended": <true/false>,
            "description": "<2-3 sentence description>",
            "technologies": ["<tech1>", "<tech2>", ...],
            "pros": ["<pro1>", "<pro2>", ...],
            "cons": ["<con1>", "<con2>", ...],
            "effort_estimate": "<e.g., '4-6 weeks for MVP'>",
            "best_for": "<when to choose this option>"
        }}
    ],
    "recommendation_reasoning": "<why the recommended option is best>",
    "questions_for_user": ["<optional clarifying questions about architecture>"]
}}
"""


async def architecture_exploration_node(state: RequirementState) -> dict:
    """
    Explore architecture options based on gathered requirements.

    This node:
    1. Loads Architect persona knowledge
    2. Analyzes requirements and constraints
    3. Generates 2-3 architecture options with trade-offs
    4. Recommends one option with reasoning
    5. Formats for user presentation

    This is Phase 3 of the multi-phase workflow.
    """
    # Check if user has selected an option
    selected_option = state.get("selected_option")
    existing_options = state.get("architecture_options", [])

    if selected_option and existing_options:
        # User is selecting from existing options
        import re
        match = re.match(r'^(option\s*)?([abc123])\s*$', selected_option.lower())
        if match:
            selection = match.group(2).upper()
            option_map = {"A": 0, "B": 1, "C": 2, "1": 0, "2": 1, "3": 2}
            idx = option_map.get(selection, 0)

            if idx < len(existing_options):
                chosen = existing_options[idx]
                logger.info(
                    "architecture_option_selected",
                    option=selection,
                    name=chosen.get("name", "Unknown"),
                )

                # Update phase history
                phase_history = list(state.get("phase_history", []))

                return {
                    "current_phase": WorkflowPhase.ARCHITECTURE.value,
                    "phase_history": phase_history,
                    "selected_architecture": chosen,
                    "response": f"✅ *Selected: {chosen.get('name', 'Option ' + selection)}*\n\n"
                               f"_{chosen.get('description', '')}_\n\n"
                               f"Moving to scope definition...",
                    "should_respond": True,
                    "active_persona": "architect",
                }

    logger.info(
        "architecture_exploration",
        channel_id=state.get("channel_id"),
        requirements_count=len(state.get("discovered_requirements", [])),
    )

    llm = get_llm_for_state(state, temperature=0.4)

    # Always use architect persona for this node
    persona_knowledge = get_persona_knowledge("architect", state)

    # Build requirements summary
    requirements = state.get("discovered_requirements", [])
    req_str = "\n".join(
        f"- [{r.get('type')}] {r.get('description')}"
        for r in requirements
    ) if requirements else "No specific requirements captured yet."

    prompt = ChatPromptTemplate.from_template(ARCHITECTURE_PROMPT)
    messages = prompt.format_messages(
        goal=state.get("current_goal") or "Not yet established",
        requirements=req_str,
        user_message=state.get("message", ""),
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        options = result.get("options", [])
        analysis = result.get("analysis_summary", "")
        reasoning = result.get("recommendation_reasoning", "")
        questions = result.get("questions_for_user", [])

        logger.info(
            "architecture_options_generated",
            options_count=len(options),
            has_recommendation=any(o.get("recommended") for o in options),
        )

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.ARCHITECTURE.value not in phase_history:
            phase_history.append(WorkflowPhase.ARCHITECTURE.value)

        # Format response for Slack
        response_text = _format_architecture_options(options, analysis, reasoning)

        # Add questions if any
        if questions:
            response_text += "\n\n*Questions to consider:*\n"
            for q in questions:
                response_text += f"• {q}\n"

        response_text += "\n\nWhich approach would you like to proceed with? Reply with A, B, C or ask questions."

        return {
            "current_phase": WorkflowPhase.ARCHITECTURE.value,
            "phase_history": phase_history,
            "architecture_options": options,
            "response": response_text,
            "should_respond": True,
            "response_target": determine_response_target(state, new_phase="architecture"),
            "active_persona": "architect",
        }

    except Exception as e:
        logger.error("architecture_exploration_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.ARCHITECTURE.value,
            "error": f"Architecture exploration failed: {str(e)}",
        }


def _format_architecture_options(
    options: list[dict],
    analysis: str,
    reasoning: str,
) -> str:
    """Format architecture options for Slack display."""
    lines = ["*Architecture Options*\n"]

    if analysis:
        lines.append(f"_{analysis}_\n")

    option_letters = ["A", "B", "C", "D"]

    for i, opt in enumerate(options):
        letter = option_letters[i] if i < len(option_letters) else str(i + 1)
        recommended = " ⭐ Recommended" if opt.get("recommended") else ""

        lines.append(f"\n*Option {letter}: {opt.get('name', 'Unnamed')}{recommended}*")
        lines.append(f"├─ {opt.get('description', '')}")

        # Technologies
        techs = opt.get("technologies", [])
        if techs:
            lines.append(f"├─ Technologies: {', '.join(techs)}")

        # Pros
        pros = opt.get("pros", [])
        for pro in pros[:3]:  # Limit to 3
            lines.append(f"├─ ✅ {pro}")

        # Cons
        cons = opt.get("cons", [])
        for con in cons[:2]:  # Limit to 2
            lines.append(f"├─ ⚠️ {con}")

        # Estimate
        estimate = opt.get("effort_estimate")
        if estimate:
            lines.append(f"└─ Estimate: {estimate}")

    if reasoning:
        lines.append(f"\n*Recommendation:* {reasoning}")

    return "\n".join(lines)

