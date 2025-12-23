"""Analysis nodes: estimation, security, validation."""

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
    logger,
    settings,
)

# =============================================================================
# Estimation Node (Phase 7)
# =============================================================================

ESTIMATION_PROMPT = """You are an expert at software project estimation.
{persona_knowledge}

## Context
Goal: {goal}
Architecture: {architecture}
Stories: {story_count} stories
Tasks: {task_count} tasks
Task Details:
{tasks}

## Your Task
Provide comprehensive estimation:
1. Story points per story (Fibonacci: 1,2,3,5,8,13,21)
2. Hours per task
3. Risk buffer percentage
4. Total project estimate

## Guidelines
- Be realistic, not optimistic
- Factor in complexity and unknowns
- Consider team ramp-up time
- Add buffer for testing and bug fixes
- Account for meetings, reviews, documentation

Respond in JSON format:
{{
    "story_estimates": [
        {{
            "story_index": <index>,
            "story_points": <fibonacci number>,
            "reasoning": "<brief explanation>"
        }}
    ],
    "task_estimates": [
        {{
            "task_index": <index>,
            "hours": <number>,
            "confidence": "<high|medium|low>"
        }}
    ],
    "totals": {{
        "total_story_points": <sum>,
        "total_hours": <sum>,
        "risk_buffer_percent": <10-50>,
        "total_with_buffer": <total hours with buffer>
    }},
    "assumptions": ["<assumption 1>", ...],
    "risks_to_estimate": ["<risk that could affect timeline 1>", ...]
}}
"""


async def estimation_node(state: RequirementState) -> dict:
    """
    Estimate effort for stories and tasks.

    This node:
    1. Assigns story points to stories
    2. Estimates hours for tasks
    3. Calculates risk buffer
    4. Produces total project estimate

    This is Phase 7 of the multi-phase workflow.
    """
    logger.info(
        "estimation",
        channel_id=state.get("channel_id"),
        story_count=len(state.get("stories", [])),
        task_count=len(state.get("tasks", [])),
    )

    llm = get_llm_for_state(state, temperature=0.2)

    # Use architect persona for estimation
    persona_knowledge = get_persona_knowledge("architect", state)

    # Format tasks
    tasks = state.get("tasks", [])
    tasks_str = "\n".join(
        f"{i}. [{t.get('complexity', 'M')}] {t.get('title', 'Untitled')}: {t.get('description', '')[:100]}"
        for i, t in enumerate(tasks)
    ) if tasks else "No tasks defined."

    # Get architecture
    chosen = state.get("chosen_architecture")
    arch_options = state.get("architecture_options", [])
    arch_str = "Not specified"
    if chosen:
        for opt in arch_options:
            if opt.get("name") == chosen:
                arch_str = opt.get("description", chosen)
                break

    prompt = ChatPromptTemplate.from_template(ESTIMATION_PROMPT)
    messages = prompt.format_messages(
        goal=state.get("current_goal") or "Not yet established",
        architecture=arch_str,
        story_count=len(state.get("stories", [])),
        task_count=len(tasks),
        tasks=tasks_str,
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        totals = result.get("totals", {})
        story_estimates = result.get("story_estimates", [])
        task_estimates = result.get("task_estimates", [])
        assumptions = result.get("assumptions", [])
        risks = result.get("risks_to_estimate", [])

        logger.info(
            "estimation_complete",
            total_points=totals.get("total_story_points"),
            total_hours=totals.get("total_hours"),
            buffer=totals.get("risk_buffer_percent"),
        )

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.ESTIMATION.value not in phase_history:
            phase_history.append(WorkflowPhase.ESTIMATION.value)

        # Format response
        response_text = _format_estimation(totals, story_estimates, assumptions, risks)
        response_text += "\n\nDoes this estimation look reasonable? Reply 'yes' to proceed, or suggest adjustments."

        return {
            "current_phase": WorkflowPhase.ESTIMATION.value,
            "phase_history": phase_history,
            "total_story_points": totals.get("total_story_points"),
            "total_hours": totals.get("total_hours"),
            "risk_buffer_percent": totals.get("risk_buffer_percent"),
            "response": response_text,
            "should_respond": True,
        }

    except Exception as e:
        logger.error("estimation_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.ESTIMATION.value,
            "error": f"Estimation failed: {str(e)}",
        }


def _format_estimation(
    totals: dict,
    story_estimates: list[dict],
    assumptions: list[str],
    risks: list[str],
) -> str:
    """Format estimation for Slack display."""
    lines = ["*Project Estimation*\n"]

    # Summary
    total_points = totals.get("total_story_points", 0)
    total_hours = totals.get("total_hours", 0)
    buffer = totals.get("risk_buffer_percent", 20)
    total_with_buffer = totals.get("total_with_buffer", total_hours * (1 + buffer / 100))

    lines.append(f"*Total Story Points:* {total_points} SP")
    lines.append(f"*Base Hours:* {total_hours}h")
    lines.append(f"*Risk Buffer:* {buffer}%")
    lines.append(f"*Total with Buffer:* {total_with_buffer:.0f}h (~{total_with_buffer / 8:.0f} days)")

    # Story breakdown
    if story_estimates:
        lines.append("\n*Story Points Breakdown:*")
        for est in story_estimates[:5]:  # Limit to 5
            lines.append(f"  Story {est.get('story_index', '?')}: {est.get('story_points', '?')} SP")

    # Assumptions
    if assumptions:
        lines.append("\n*Assumptions:*")
        for assumption in assumptions[:3]:
            lines.append(f"  • {assumption}")

    # Risks
    if risks:
        lines.append("\n*Timeline Risks:*")
        for risk in risks[:3]:
            lines.append(f"  ⚠️ {risk}")

    return "\n".join(lines)


# =============================================================================
# Security Review Node (Phase 8)
# =============================================================================

SECURITY_REVIEW_PROMPT = """You are a security analyst reviewing requirements for security concerns.
{persona_knowledge}

## Context
Goal: {goal}
Architecture: {architecture}
Stories: {story_count} stories
Tasks: {task_count} tasks

Story Details:
{stories}

## Your Task
Perform a security review:
1. Identify security concerns in the requirements
2. Check for OWASP Top 10 risks
3. Evaluate authentication/authorization needs
4. Check data protection requirements
5. Suggest security stories/tasks if missing

## Security Checklist
- Authentication & Authorization
- Input validation
- Data encryption (at rest, in transit)
- Logging & Audit trails
- Session management
- Error handling (no info leakage)
- Dependency security
- API security

Respond in JSON format:
{{
    "security_rating": "<low|medium|high|critical>",
    "concerns": [
        {{
            "category": "<OWASP category or custom>",
            "description": "<what the concern is>",
            "severity": "<low|medium|high|critical>",
            "affected_stories": [<story indices>],
            "recommendation": "<how to address>"
        }}
    ],
    "missing_requirements": [
        {{
            "title": "<security story/task title>",
            "description": "<what needs to be added>",
            "type": "<Story|Task>",
            "priority": "Must"
        }}
    ],
    "checklist_status": {{
        "authentication": "<pass|fail|partial|n/a>",
        "authorization": "<pass|fail|partial|n/a>",
        "input_validation": "<pass|fail|partial|n/a>",
        "data_encryption": "<pass|fail|partial|n/a>",
        "logging": "<pass|fail|partial|n/a>",
        "error_handling": "<pass|fail|partial|n/a>"
    }},
    "overall_assessment": "<1-2 sentence summary>"
}}
"""


async def security_review_node(state: RequirementState) -> dict:
    """
    Perform security review of requirements.

    This node:
    1. Uses Security Analyst persona
    2. Reviews stories/tasks for security concerns
    3. Checks against OWASP Top 10
    4. Suggests security stories/tasks if missing

    This is Phase 8 of the multi-phase workflow.
    """
    logger.info(
        "security_review",
        channel_id=state.get("channel_id"),
        story_count=len(state.get("stories", [])),
    )

    llm = get_llm_for_state(state, temperature=0.2)

    # Use security_analyst persona
    persona_knowledge = get_persona_knowledge("security_analyst", state)

    # Format stories
    stories = state.get("stories", [])
    stories_str = "\n".join(
        f"{i}. {s.get('title', 'Untitled')}: {s.get('i_want', '')}"
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

    prompt = ChatPromptTemplate.from_template(SECURITY_REVIEW_PROMPT)
    messages = prompt.format_messages(
        goal=state.get("current_goal") or "Not yet established",
        architecture=arch_str,
        story_count=len(stories),
        task_count=len(state.get("tasks", [])),
        stories=stories_str,
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        rating = result.get("security_rating", "medium")
        concerns = result.get("concerns", [])
        missing = result.get("missing_requirements", [])
        checklist = result.get("checklist_status", {})
        assessment = result.get("overall_assessment", "")

        logger.info(
            "security_review_complete",
            rating=rating,
            concern_count=len(concerns),
            missing_count=len(missing),
        )

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.SECURITY.value not in phase_history:
            phase_history.append(WorkflowPhase.SECURITY.value)

        # Format response
        response_text = _format_security_review(rating, concerns, missing, checklist, assessment)

        return {
            "current_phase": WorkflowPhase.SECURITY.value,
            "phase_history": phase_history,
            "response": response_text,
            "should_respond": True,
            "active_persona": "security_analyst",
        }

    except Exception as e:
        logger.error("security_review_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.SECURITY.value,
            "error": f"Security review failed: {str(e)}",
        }


def _format_security_review(
    rating: str,
    concerns: list[dict],
    missing: list[dict],
    checklist: dict,
    assessment: str,
) -> str:
    """Format security review for Slack display."""
    rating_emoji = {
        "low": "🟢",
        "medium": "🟡",
        "high": "🟠",
        "critical": "🔴",
    }.get(rating, "⚪")

    lines = [f"*Security Review* {rating_emoji} {rating.upper()}\n"]

    if assessment:
        lines.append(f"_{assessment}_\n")

    # Checklist
    lines.append("*Security Checklist:*")
    status_emoji = {"pass": "✅", "fail": "❌", "partial": "⚠️", "n/a": "➖"}
    for item, status in checklist.items():
        emoji = status_emoji.get(status, "❓")
        lines.append(f"  {emoji} {item.replace('_', ' ').title()}")

    # Concerns
    if concerns:
        lines.append("\n*Security Concerns:*")
        for c in concerns[:5]:
            severity_emoji = {"low": "🟢", "medium": "🟡", "high": "🟠", "critical": "🔴"}.get(c.get("severity", ""), "⚪")
            lines.append(f"\n{severity_emoji} *{c.get('category', 'Unknown')}*")
            lines.append(f"  {c.get('description', '')}")
            if c.get("recommendation"):
                lines.append(f"  → {c.get('recommendation')}")

    # Missing requirements
    if missing:
        lines.append("\n*Suggested Security Items:*")
        for m in missing[:3]:
            lines.append(f"  + [{m.get('type', 'Task')}] {m.get('title', 'Untitled')}")

    lines.append("\n\nProceed to validation? Reply 'yes' or ask about specific concerns.")

    return "\n".join(lines)


# =============================================================================
# Validation Node (Phase 9)
# =============================================================================

VALIDATION_PROMPT = """You are a QA lead validating requirements completeness and quality.

## Context
Goal: {goal}
Epics: {epic_count}
Stories: {story_count}
Tasks: {task_count}

Epic Details:
{epics}

Story Details:
{stories}

## Your Task
Validate the requirements package:
1. Check for gaps in requirements coverage
2. Verify INVEST criteria for stories
3. Check dependency completeness
4. Verify acceptance criteria quality
5. Check for missing non-functional requirements

## INVEST Criteria
- Independent: Can be developed separately
- Negotiable: Not a contract, open to discussion
- Valuable: Delivers value to user/business
- Estimable: Clear enough to estimate
- Small: Fits in a sprint
- Testable: Has clear acceptance criteria

Respond in JSON format:
{{
    "validation_passed": <true/false>,
    "overall_score": <0-100>,
    "gaps": [
        {{
            "type": "<functional|non-functional|integration|edge-case>",
            "description": "<what's missing>",
            "severity": "<low|medium|high>",
            "suggestion": "<how to fix>"
        }}
    ],
    "invest_violations": [
        {{
            "story_index": <index>,
            "violations": ["<I|N|V|E|S|T>"],
            "explanation": "<why it violates>"
        }}
    ],
    "acceptance_criteria_issues": [
        {{
            "story_index": <index>,
            "issue": "<what's wrong with AC>"
        }}
    ],
    "warnings": ["<warning 1>", ...],
    "ready_for_development": <true/false>,
    "summary": "<overall assessment>"
}}
"""


async def validation_node(state: RequirementState) -> dict:
    """
    Validate requirements completeness and quality.

    This node:
    1. Checks for gaps in coverage
    2. Verifies INVEST criteria
    3. Validates acceptance criteria
    4. Produces validation report

    This is Phase 9 of the multi-phase workflow.
    """
    logger.info(
        "validation",
        channel_id=state.get("channel_id"),
        story_count=len(state.get("stories", [])),
    )

    llm = get_llm_for_state(state, temperature=0.2)

    # Format epics
    epics = state.get("epics", [])
    epics_str = "\n".join(
        f"{i}. {e.get('title', 'Untitled')}: {e.get('description', '')}"
        for i, e in enumerate(epics)
    ) if epics else "No epics defined."

    # Format stories with acceptance criteria
    stories = state.get("stories", [])
    stories_str = ""
    for i, s in enumerate(stories):
        stories_str += f"\n{i}. {s.get('title', 'Untitled')}"
        stories_str += f"\n   As a {s.get('as_a', '...')}, I want {s.get('i_want', '...')}"
        ac = s.get("acceptance_criteria", [])
        if ac:
            stories_str += "\n   AC: " + "; ".join(ac[:3])

    prompt = ChatPromptTemplate.from_template(VALIDATION_PROMPT)
    messages = prompt.format_messages(
        goal=state.get("current_goal") or "Not yet established",
        epic_count=len(epics),
        story_count=len(stories),
        task_count=len(state.get("tasks", [])),
        epics=epics_str,
        stories=stories_str or "No stories defined.",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        passed = result.get("validation_passed", False)
        score = result.get("overall_score", 0)
        gaps = result.get("gaps", [])
        invest_violations = result.get("invest_violations", [])
        warnings = result.get("warnings", [])
        ready = result.get("ready_for_development", False)
        summary = result.get("summary", "")

        logger.info(
            "validation_complete",
            passed=passed,
            score=score,
            gap_count=len(gaps),
            ready=ready,
        )

        # Update phase history
        phase_history = list(state.get("phase_history", []))
        if WorkflowPhase.VALIDATION.value not in phase_history:
            phase_history.append(WorkflowPhase.VALIDATION.value)

        # Build validation report
        validation_report = {
            "passed": passed,
            "score": score,
            "gaps": gaps,
            "invest_violations": invest_violations,
            "warnings": warnings,
            "ready": ready,
        }

        # Format response
        response_text = _format_validation(passed, score, gaps, invest_violations, warnings, summary)

        return {
            "current_phase": WorkflowPhase.VALIDATION.value,
            "phase_history": phase_history,
            "validation_report": validation_report,
            "response": response_text,
            "should_respond": True,
        }

    except Exception as e:
        logger.error("validation_failed", error=str(e))
        return {
            "current_phase": WorkflowPhase.VALIDATION.value,
            "error": f"Validation failed: {str(e)}",
        }


def _format_validation(
    passed: bool,
    score: int,
    gaps: list[dict],
    invest_violations: list[dict],
    warnings: list[str],
    summary: str,
) -> str:
    """Format validation report for Slack display."""
    status = "✅ PASSED" if passed else "❌ NEEDS ATTENTION"

    lines = [f"*Validation Report* {status}\n"]
    lines.append(f"*Quality Score:* {score}/100\n")

    if summary:
        lines.append(f"_{summary}_\n")

    # Gaps
    if gaps:
        lines.append("*Gaps Found:*")
        for g in gaps[:4]:
            severity_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(g.get("severity", ""), "⚪")
            lines.append(f"  {severity_emoji} [{g.get('type', 'unknown')}] {g.get('description', '')}")

    # INVEST violations
    if invest_violations:
        lines.append("\n*INVEST Violations:*")
        for v in invest_violations[:3]:
            violations = ", ".join(v.get("violations", []))
            lines.append(f"  Story {v.get('story_index', '?')}: {violations} - {v.get('explanation', '')}")

    # Warnings
    if warnings:
        lines.append("\n*Warnings:*")
        for w in warnings[:3]:
            lines.append(f"  ⚠️ {w}")

    if passed:
        lines.append("\n\n✅ Ready for final review! Reply 'yes' to proceed.")
    else:
        lines.append("\n\n⚠️ Issues found. Would you like to address them or proceed anyway?")

    return "\n".join(lines)

