"""Drafting nodes: conflict detection, draft, critique."""

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
    settings,
)

# =============================================================================
# Conflict Detection Node
# =============================================================================

CONFLICT_DETECTION_PROMPT = """Analyze the new requirement against existing requirements and identify any conflicts.

Types of conflicts to detect:
1. contradiction: New requirement directly contradicts an existing one
2. duplicate: New requirement is essentially the same as existing
3. overlap: Significant overlap that needs clarification

New requirement:
{new_requirement}

Existing requirements:
{existing_requirements}

Respond in JSON format:
{{
    "conflicts": [
        {{
            "existing_id": "<id>",
            "existing_summary": "<summary>",
            "conflict_type": "<type>",
            "description": "<explanation>"
        }}
    ],
    "has_conflicts": <true/false>
}}

If no conflicts, return {{"conflicts": [], "has_conflicts": false}}
"""


async def conflict_detection_node(state: RequirementState) -> dict:
    """
    Check for conflicts between new requirement and existing ones.

    Searches Zep and Jira for related requirements and uses LLM to detect conflicts.

    IMPORTANT: When no conflicts are found, this node sets awaiting_human=True because
    the next node (human_approval) uses interrupt_before and won't run until resumed.
    """
    print(f"[DEBUG] conflict_detection_node called, has_draft={bool(state.get('draft'))}")

    # Skip if no draft to check
    if not state.get("draft"):
        print(f"[DEBUG] conflict_detection: no draft, returning empty")
        return {"conflicts": []}

    logger.info("detecting_conflicts", channel_id=state.get("channel_id"))

    llm = get_llm_for_state(state, temperature=0.1)

    # Build existing requirements from memory and Jira
    existing = []
    for fact in state.get("zep_facts", [])[:20]:
        existing.append(f"- {fact.get('content', '')}")

    for issue in state.get("related_jira_issues", [])[:10]:
        existing.append(f"- [{issue.get('key')}] {issue.get('summary', '')}")

    if not existing:
        # No existing requirements to check against - proceed to human approval
        print(f"[DEBUG] conflict_detection: no existing requirements, setting awaiting_human=True")
        return {"conflicts": [], "awaiting_human": True}

    draft = state.get("draft", {})
    new_req = f"Title: {draft.get('title', '')}\nDescription: {draft.get('description', '')}"

    prompt = ChatPromptTemplate.from_template(CONFLICT_DETECTION_PROMPT)
    messages = prompt.format_messages(
        new_requirement=new_req,
        existing_requirements="\n".join(existing),
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        conflicts = result.get("conflicts", [])
        logger.info("conflicts_detected", count=len(conflicts))

        # If no conflicts, we're heading to human_approval which uses interrupt_before
        # Set awaiting_human=True so handlers.py knows to show approval buttons
        if not conflicts:
            print(f"[DEBUG] conflict_detection: no conflicts found, setting awaiting_human=True")
            return {"conflicts": [], "awaiting_human": True}

        print(f"[DEBUG] conflict_detection: {len(conflicts)} conflicts found")
        return {"conflicts": conflicts}

    except Exception as e:
        logger.error("conflict_detection_failed", error=str(e))
        return {"conflicts": [], "error": f"Conflict detection failed: {str(e)}"}


# =============================================================================
# Draft Node
# =============================================================================

DRAFT_REQUIREMENT_PROMPT = """You are a requirements engineering expert.
{persona_knowledge}

Analyze the user's input and create well-structured requirements.

## IMPORTANT: Sizing Guidelines
- **Epic**: Large initiative spanning multiple sprints, contains 5+ distinct features/user flows
- **Story**: Single user-facing feature completable in 1-2 sprints
- **Task**: Technical work item, usually 1-3 days

## Auto-Split Rules
If the user describes a complex system with multiple distinct features, roles, or workflows:
1. Create ONE Epic as the parent container
2. Break it down into multiple Stories (3-7 stories typically)
3. Each Story should be independently deliverable

For simpler requests, create a single Story or Task.

## Format
Use user story format: "As a [user type], I want [goal], so that [benefit]."

Include clear acceptance criteria that are:
- Specific and measurable
- Testable by QA
- Unambiguous

User message: {message}

Context from conversation:
{context}

Current goal/scope: {goal}

Respond in JSON format. For complex requirements, use the "requirements" array:
{{
    "is_complex": <true if needs splitting into Epic + Stories>,
    "requirements": [
        {{
            "title": "<concise title>",
            "description": "<full description>",
            "issue_type": "<Epic|Story|Task|Bug>",
            "acceptance_criteria": ["<criterion 1>", ...],
            "priority": "<low|medium|high|critical>",
            "labels": ["<label1>", ...],
            "parent_index": <null for Epic, 0 for children of first Epic>
        }}
    ],
    "reasoning": "<explain the structure and why you chose this breakdown>"
}}

For simple requirements, you can return a single item in the array.
"""


async def draft_node(state: RequirementState) -> dict:
    """
    Create or refine requirement draft(s) based on user input.

    Now supports:
    - Persona-specific knowledge
    - Auto-splitting complex requirements into Epic + Stories
    """
    logger.info(
        "drafting_requirement",
        channel_id=state.get("channel_id"),
        iteration=state.get("iteration_count", 0),
    )

    llm = get_llm_for_state(state, temperature=0.3)

    # Get persona knowledge if active
    persona_name = state.get("active_persona")
    persona_knowledge = get_persona_knowledge(persona_name, state)

    # Build context
    context = ""
    for fact in state.get("zep_facts", [])[:5]:
        context += f"- {fact.get('content', '')}\n"

    # Include previous feedback if refining
    if state.get("critique_feedback"):
        context += "\nPrevious feedback to address:\n"
        for feedback in state["critique_feedback"]:
            context += f"- {feedback}\n"

    prompt = ChatPromptTemplate.from_template(DRAFT_REQUIREMENT_PROMPT)
    messages = prompt.format_messages(
        message=state.get("message", ""),
        context=context or "No additional context.",
        goal=state.get("current_goal") or "Not yet established",
        persona_knowledge=persona_knowledge or "",
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        requirements = result.get("requirements", [])
        is_complex = result.get("is_complex", False)

        if not requirements:
            # Fallback for old format
            requirements = [result]

        # Process requirements
        drafts = []
        for req in requirements:
            draft = {
                "title": req.get("title", ""),
                "description": req.get("description", ""),
                "issue_type": req.get("issue_type", "Story"),
                "acceptance_criteria": req.get("acceptance_criteria", []),
                "priority": req.get("priority", "medium"),
                "labels": req.get("labels", []),
                "parent_index": req.get("parent_index"),
            }
            drafts.append(draft)

        # For now, use the first draft as the main one
        # (multi-draft handling will be added to approval flow)
        main_draft = drafts[0] if drafts else {}

        logger.info(
            "draft_created",
            title=main_draft.get("title"),
            issue_type=main_draft.get("issue_type"),
            total_drafts=len(drafts),
            is_complex=is_complex,
        )

        return {
            "draft": main_draft,
            "all_drafts": drafts if len(drafts) > 1 else None,
            "is_complex_requirement": is_complex,
            "iteration_count": state.get("iteration_count", 0) + 1,
        }

    except Exception as e:
        logger.error("draft_creation_failed", error=str(e))
        return {"error": f"Draft creation failed: {str(e)}"}


# =============================================================================
# Critique Node (Reflexion)
# =============================================================================

CRITIQUE_PROMPT = """You are a strict QA reviewer for requirements. Critically evaluate this requirement draft.

Check for:
1. Clarity: Is it unambiguous?
2. Completeness: Are all necessary details included?
3. Testability: Can acceptance criteria be verified?
4. INVEST principles: Independent, Negotiable, Valuable, Estimable, Small, Testable
5. User story format (if applicable): As a..., I want..., so that...

Requirement draft:
Title: {title}
Description: {description}
Type: {issue_type}
Acceptance Criteria: {acceptance_criteria}
Priority: {priority}

Respond in JSON format:
{{
    "is_acceptable": <true/false>,
    "issues": ["<issue 1>", "<issue 2>", ...],
    "suggestions": ["<suggestion 1>", "<suggestion 2>", ...],
    "overall_quality": "<poor|fair|good|excellent>"
}}

Be strict but fair. Minor issues should still pass if the core requirement is clear.
"""


async def critique_node(state: RequirementState) -> dict:
    """
    Critique the requirement draft and provide feedback.

    Returns whether draft is acceptable or needs refinement.
    """
    draft = state.get("draft")
    if not draft:
        return {"critique_feedback": ["No draft to critique"]}

    logger.info(
        "critiquing_draft",
        channel_id=state.get("channel_id"),
        iteration=state.get("iteration_count", 0),
    )

    llm = get_llm_for_state(state, temperature=0.2)

    prompt = ChatPromptTemplate.from_template(CRITIQUE_PROMPT)
    messages = prompt.format_messages(
        title=draft.get("title", ""),
        description=draft.get("description", ""),
        issue_type=draft.get("issue_type", ""),
        acceptance_criteria="\n".join(draft.get("acceptance_criteria", [])),
        priority=draft.get("priority", ""),
    )

    try:
        response = await llm.ainvoke(messages)
        result = parse_llm_json_response(response)

        is_acceptable = result.get("is_acceptable", False)
        issues = result.get("issues", [])
        suggestions = result.get("suggestions", [])

        logger.info(
            "critique_complete",
            is_acceptable=is_acceptable,
            issue_count=len(issues),
        )

        # Combine issues and suggestions as feedback
        feedback = issues + suggestions

        return {
            "critique_feedback": feedback if not is_acceptable else [],
        }

    except Exception as e:
        logger.error("critique_failed", error=str(e))
        return {"critique_feedback": [], "error": f"Critique failed: {str(e)}"}

