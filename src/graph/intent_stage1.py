"""Stage 1: Mode classification (Phase 39).

Lightweight LLM call that:
1. Classifies SuperMode (BUILD/OPERATE/DECIDE/THINK/CHAT)
2. Detects multi-intent signal
3. Returns top candidates with scores

This is the "cheap" stage - short prompt, minimal context.
"""
import json
import logging
from typing import Optional
from dataclasses import dataclass

from src.schemas.intent import SuperMode

logger = logging.getLogger(__name__)


@dataclass
class ModeCandidate:
    """Single mode candidate with score."""
    mode: SuperMode
    score: float


@dataclass
class Stage1Result:
    """Output of Stage 1 mode classification."""
    mode_candidates: list[ModeCandidate]
    multi_intent: bool
    reasons: list[str]

    @property
    def top_mode(self) -> SuperMode:
        """Get highest-scored mode."""
        if not self.mode_candidates:
            return SuperMode.CHAT
        return max(self.mode_candidates, key=lambda c: c.score).mode

    @property
    def top_score(self) -> float:
        """Get highest score."""
        if not self.mode_candidates:
            return 0.5
        return max(c.score for c in self.mode_candidates)

    @property
    def margin(self) -> float:
        """Get margin between top two candidates."""
        if len(self.mode_candidates) < 2:
            return 1.0
        scores = sorted([c.score for c in self.mode_candidates], reverse=True)
        return scores[0] - scores[1]


# Stage 1 prompt - kept minimal for speed
STAGE1_PROMPT = """Classify user message into one of 5 modes:

BUILD - Creating/modifying draft, work items, structure
OPERATE - Managing Jira, syncing, commands on existing tickets
DECIDE - Recording decisions, approvals
THINK - Analysis, review, help thinking through problems
CHAT - Greetings, questions about bot, casual

Also detect if message contains MULTIPLE distinct requests (multi-intent).

MESSAGE: "{message}"
{context_hint}

Return JSON only:
{{"modes": [{{"mode": "BUILD", "score": 0.8}}, ...], "multi_intent": false, "reasons": ["..."]}}

Rules:
- Return 2-3 most likely modes with scores (0.0-1.0)
- multi_intent=true if conjunctions like "and", "also", "plus" combine distinct requests
- Keep reasons brief (1-2 sentences)"""


async def classify_mode(
    message: str,
    context_hint: Optional[str] = None,
) -> Stage1Result:
    """Stage 1: Classify user message into SuperMode.

    Args:
        message: User's message text
        context_hint: Optional hint about active state (e.g., "active draft exists")

    Returns:
        Stage1Result with mode candidates, multi_intent flag, reasons
    """
    from src.llm import get_llm

    llm = get_llm()

    # Build prompt
    hint_str = f"\nCONTEXT: {context_hint}" if context_hint else ""
    prompt = STAGE1_PROMPT.format(message=message, context_hint=hint_str)

    try:
        result = await llm.chat(prompt)

        # Parse JSON response
        result = result.strip()
        if result.startswith("```"):
            lines = result.split("\n")
            result = "\n".join(lines[1:])
        if result.endswith("```"):
            result = result[:-3]
        result = result.strip()

        data = json.loads(result)

        # Parse mode candidates
        modes_data = data.get("modes", [])
        candidates = []
        for item in modes_data:
            mode_str = item.get("mode", "CHAT").upper()
            try:
                mode = SuperMode(mode_str.lower())
            except ValueError:
                mode = SuperMode.CHAT
            score = float(item.get("score", 0.5))
            candidates.append(ModeCandidate(mode=mode, score=score))

        # Ensure at least one candidate
        if not candidates:
            candidates = [ModeCandidate(mode=SuperMode.CHAT, score=0.5)]

        return Stage1Result(
            mode_candidates=candidates,
            multi_intent=data.get("multi_intent", False),
            reasons=data.get("reasons", []),
        )

    except Exception as e:
        logger.warning(f"Stage 1 classification failed: {e}, defaulting to CHAT")
        return Stage1Result(
            mode_candidates=[ModeCandidate(mode=SuperMode.CHAT, score=0.5)],
            multi_intent=False,
            reasons=[f"Stage 1 failed: {str(e)[:100]}"],
        )


def build_context_hint(
    has_draft: bool = False,
    has_taskplan: bool = False,
    anchor_type: Optional[str] = None,
) -> Optional[str]:
    """Build context hint for Stage 1 classifier.

    These hints help Stage 1 prioritize correctly without
    full context injection (that's Stage 2's job).
    """
    hints = []
    if has_draft:
        hints.append("Active draft exists")
    if has_taskplan:
        hints.append("Active TaskPlan in progress")
    if anchor_type:
        hints.append(f"In {anchor_type} thread")

    return ". ".join(hints) if hints else None


def get_stage2_hints(stage1: Stage1Result) -> dict:
    """Extract hints from Stage 1 for Stage 2 classification.

    Stage 2 uses these to focus its more detailed classification.
    """
    return {
        "primary_mode": stage1.top_mode.value,
        "is_multi_intent": stage1.multi_intent,
        "mode_confidence": stage1.top_score,
        "mode_margin": stage1.margin,
        "candidate_modes": [c.mode.value for c in stage1.mode_candidates],
    }
