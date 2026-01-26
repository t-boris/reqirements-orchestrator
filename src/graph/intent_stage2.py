"""Stage 2: Intent extraction and TaskPlan decomposition (Phase 39).

Full LLM classification that:
1. Extracts specific intent within mode
2. Identifies targets (jira_key, decision_id, workitem_id)
3. Decomposes multi-intent into TaskPlan
4. Returns IntentEnvelope (single/plan/ambiguous)

This is the "detailed" stage - fuller prompt, more context.
"""
import json
import logging
from typing import Any, Optional

from src.schemas.intent import Intent, SuperMode
from src.schemas.intent_envelope import (
    IntentEnvelope,
    EnvelopeKind,
    RiskLevel,
    TargetReference,
    IntentCandidate,
    TaskEnvelope,
    AmbiguousChoice,
)
from src.graph.intent_stage1 import Stage1Result

logger = logging.getLogger(__name__)


# Intent mappings per mode
MODE_INTENTS: dict[SuperMode, list[Intent]] = {
    SuperMode.BUILD: [Intent.DRAFT_REFINE, Intent.DRAFT_TRANSFORM, Intent.WORKITEM_CREATE],
    SuperMode.THINK: [Intent.REVIEW],
    SuperMode.DECIDE: [Intent.DECISION, Intent.DECISION, Intent.DECISION],
    SuperMode.OPERATE: [Intent.JIRA_COMMAND, Intent.JIRA_SEARCH, Intent.SYNC_REQUEST, Intent.TICKET_ACTION],
    SuperMode.CHAT: [Intent.DISCUSSION, Intent.META],
}

# Risk levels by intent
INTENT_RISK: dict[Intent, RiskLevel] = {
    # Safe (read-only)
    Intent.REVIEW: RiskLevel.SAFE,
    Intent.DISCUSSION: RiskLevel.SAFE,
    Intent.META: RiskLevel.SAFE,
    Intent.JIRA_SEARCH: RiskLevel.SAFE,
    # Write (single Jira)
    Intent.DRAFT_REFINE: RiskLevel.SAFE,
    Intent.DRAFT_TRANSFORM: RiskLevel.SAFE,
    Intent.WORKITEM_CREATE: RiskLevel.WRITE,
    Intent.DECISION: RiskLevel.WRITE,
    Intent.JIRA_COMMAND: RiskLevel.WRITE,
    Intent.TICKET_ACTION: RiskLevel.WRITE,
    Intent.SYNC_REQUEST: RiskLevel.WRITE,
}


# Stage 2 prompt template
STAGE2_PROMPT = """You are classifying a user message into a specific intent.

MODE: {mode}
CANDIDATE_INTENTS: {intents}

MESSAGE: "{message}"

CONTEXT:
{context}

STATE:
- Has draft: {has_draft}
- Has anchor: {anchor_type}
- Is multi-intent signal: {multi_intent}

TASK:
1. Choose the best intent from CANDIDATE_INTENTS
2. Extract any explicit targets (Jira key, decision ID, workitem ID)
3. If multi-intent, decompose into ordered tasks
4. Assess risk level for each action

Return JSON:
{{
  "kind": "single|plan|ambiguous",

  // For single:
  "intent": "INTENT_NAME",
  "targets": {{"jira_key": null, "decision_id": null, "workitem_id": null}},
  "params": {{}},
  "confidence": 0.0,
  "margin": 0.0,
  "reason": "why this intent",
  "alternatives": [{{"intent": "...", "score": 0.0}}],

  // For plan (if multi_intent):
  "tasks": [
    {{"intent": "...", "targets": {{}}, "params": {{}}, "reason": "..."}}
  ],

  // For ambiguous:
  "choices": [
    {{"label": "...", "intent": "...", "targets": {{}}}}
  ],
  "ambiguous_reason": "why unclear"
}}

Rules:
- Only use intents from CANDIDATE_INTENTS
- targets must be explicit from message (don't invent IDs)
- For plan: order tasks safely (reads before writes)
- confidence 0.0-1.0, margin = top - second score"""


async def classify_intent(
    message: str,
    stage1: Stage1Result,
    context: str = "",
    has_draft: bool = False,
    anchor_type: Optional[str] = None,
    anchor_id: Optional[str] = None,
) -> IntentEnvelope:
    """Stage 2: Extract specific intent and targets.

    Args:
        message: User's message text
        stage1: Output from Stage 1 mode classification
        context: Relevant context string (history, artifacts)
        has_draft: Whether active draft exists
        anchor_type: Thread anchor type (DECISION, WORKITEM, JIRA, None)
        anchor_id: Thread anchor ID if applicable

    Returns:
        IntentEnvelope with full classification result
    """
    from src.llm import get_llm

    mode = stage1.top_mode
    intents = MODE_INTENTS.get(mode, [Intent.DISCUSSION])
    intent_names = [i.value.upper() for i in intents]

    llm = get_llm()

    prompt = STAGE2_PROMPT.format(
        mode=mode.value.upper(),
        intents=", ".join(intent_names),
        message=message,
        context=context[:2000] if context else "None",
        has_draft=has_draft,
        anchor_type=anchor_type or "None",
        multi_intent=stage1.multi_intent,
    )

    try:
        result = await llm.chat(prompt)
        data = _parse_json(result)

        kind = data.get("kind", "single")

        if kind == "plan":
            return _build_plan_envelope(data, mode)
        elif kind == "ambiguous":
            return _build_ambiguous_envelope(data, mode)
        else:
            return _build_single_envelope(data, mode, stage1)

    except Exception as e:
        logger.warning(f"Stage 2 classification failed: {e}")
        return _fallback_envelope(mode, str(e))


def _parse_json(result: str) -> dict:
    """Parse JSON from LLM response, handling code blocks."""
    result = result.strip()
    if result.startswith("```"):
        lines = result.split("\n")
        result = "\n".join(lines[1:])
    if result.endswith("```"):
        result = result[:-3]
    return json.loads(result.strip())


def _parse_intent(intent_str: str, mode: SuperMode) -> Intent:
    """Parse intent string to Intent enum."""
    try:
        return Intent(intent_str.lower())
    except ValueError:
        # Fallback to first intent for mode
        return MODE_INTENTS.get(mode, [Intent.DISCUSSION])[0]


def _parse_targets(data: dict) -> TargetReference:
    """Parse targets from LLM output."""
    targets = data.get("targets", {})
    return TargetReference(
        jira_key=targets.get("jira_key"),
        decision_id=targets.get("decision_id"),
        workitem_id=targets.get("workitem_id"),
    )


def _build_single_envelope(
    data: dict,
    mode: SuperMode,
    stage1: Stage1Result,
) -> IntentEnvelope:
    """Build single-action envelope."""
    intent = _parse_intent(data.get("intent", "discussion"), mode)
    targets = _parse_targets(data)
    confidence = float(data.get("confidence", stage1.top_score))
    margin = float(data.get("margin", stage1.margin))
    risk = INTENT_RISK.get(intent, RiskLevel.SAFE)

    # Build alternatives
    alternatives = []
    for alt in data.get("alternatives", [])[:3]:
        alt_intent = _parse_intent(alt.get("intent", "discussion"), mode)
        alternatives.append(IntentCandidate(
            mode=mode,
            intent=alt_intent,
            score=float(alt.get("score", 0.5)),
            risk_level=INTENT_RISK.get(alt_intent, RiskLevel.SAFE),
        ))

    return IntentEnvelope.single(
        mode=mode,
        intent=intent,
        confidence=confidence,
        margin=margin,
        risk_level=risk,
        targets=targets,
        params=data.get("params", {}),
        reason=data.get("reason", ""),
        alternatives=alternatives,
    )


def _build_plan_envelope(data: dict, mode: SuperMode) -> IntentEnvelope:
    """Build multi-task plan envelope."""
    tasks = []
    for task_data in data.get("tasks", []):
        intent = _parse_intent(task_data.get("intent", "discussion"), mode)
        risk = INTENT_RISK.get(intent, RiskLevel.SAFE)
        tasks.append(TaskEnvelope(
            mode=mode,
            intent=intent,
            risk_level=risk,
            targets=_parse_targets(task_data),
            params=task_data.get("params", {}),
            reason=task_data.get("reason", ""),
        ))

    # Sort tasks by risk (safe first)
    risk_order = {RiskLevel.SAFE: 0, RiskLevel.WRITE: 1, RiskLevel.MASS_WRITE: 2, RiskLevel.DESTRUCTIVE: 3}
    tasks.sort(key=lambda t: risk_order.get(t.risk_level, 1))

    confidence = float(data.get("confidence", 0.7))
    margin = float(data.get("margin", 0.2))

    return IntentEnvelope.plan(
        tasks=tasks,
        confidence=confidence,
        margin=margin,
        requires_confirm=any(t.risk_level != RiskLevel.SAFE for t in tasks),
        reason=data.get("reason", "Multi-intent request"),
    )


def _build_ambiguous_envelope(data: dict, mode: SuperMode) -> IntentEnvelope:
    """Build ambiguous envelope requiring user choice."""
    choices = []
    for choice_data in data.get("choices", [])[:4]:
        intent = _parse_intent(choice_data.get("intent", "discussion"), mode)
        choices.append(AmbiguousChoice(
            label=choice_data.get("label", intent.value),
            mode=mode,
            intent=intent,
            risk_level=INTENT_RISK.get(intent, RiskLevel.SAFE),
            targets=_parse_targets(choice_data),
            params=choice_data.get("params", {}),
        ))

    return IntentEnvelope.ambiguous(
        choices=choices,
        reason=data.get("ambiguous_reason", "Unclear intent"),
    )


def _fallback_envelope(mode: SuperMode, error: str) -> IntentEnvelope:
    """Create fallback envelope on parse error."""
    return IntentEnvelope.ambiguous(
        choices=[
            AmbiguousChoice(
                label="Just chat",
                mode=SuperMode.CHAT,
                intent=Intent.DISCUSSION,
                risk_level=RiskLevel.SAFE,
            ),
        ],
        reason=f"Classification error: {error[:100]}",
        confidence=0.3,
        margin=0.0,
    )
