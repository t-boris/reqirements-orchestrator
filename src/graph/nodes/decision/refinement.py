"""Draft refinement helpers for decision node.

Handles meta-questions about draft structure and scope.
"""
from src.schemas.draft import TicketDraft


def build_refinement_prompt(draft: TicketDraft, state: dict) -> str:
    """Build a contextual prompt for draft refinement questions.

    When user asks "is one epic enough?" or "should we split this?",
    generate a helpful response that:
    1. Acknowledges the current draft
    2. Offers options (keep as-is, split, decompose)
    3. Asks a clarifying question

    Returns:
        Prompt text for the bot to send.
    """
    draft_type = draft.get_display_type() if hasattr(draft, 'get_display_type') else "Story"
    title = draft.title or "Untitled"

    # Get conversation context for more relevant response
    context_relation = state.get("intent_result", {}).get("context_relation", "refine")

    # Build base prompt
    if draft_type.lower() == "epic":
        prompt = f"""I'm looking at your current Epic draft: *"{title}"*

Would you like to:
- **Keep as single Epic** - if the scope is clear and manageable
- **Split into multiple Epics** - if there are distinct workstreams
- **Add Stories underneath** - break down into smaller deliverables

What direction would work best for your needs?"""
    else:
        prompt = f"""I'm looking at your current {draft_type} draft: *"{title}"*

Would you like to:
- **Keep as-is** - proceed with current scope
- **Elevate to Epic** - if this represents a larger initiative
- **Break down further** - split into smaller tasks

What would you prefer?"""

    return prompt
