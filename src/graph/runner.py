"""Graph runner - manages execution and interrupt/resume flow.

Handles:
- Session-based graph execution (one run per thread)
- Interrupt at ASK/PREVIEW for human-in-the-loop
- Resume with new messages
- State persistence via checkpointer
"""
import asyncio
import logging
from typing import Optional, Any, TYPE_CHECKING
from datetime import datetime

from langchain_core.messages import HumanMessage

from src.schemas.state import AgentState, AgentPhase
from src.schemas.draft import TicketDraft
from src.graph.graph import get_compiled_graph

if TYPE_CHECKING:
    from src.slack.session import SessionIdentity

logger = logging.getLogger(__name__)


class GraphRunner:
    """Manages graph execution for a session.

    One runner per thread - handles interrupt/resume flow.
    """

    def __init__(self, identity: "SessionIdentity"):
        self.identity = identity
        self.graph = None  # Lazy init - call _ensure_graph() before use
        self._config = {
            "configurable": {
                "thread_id": identity.session_id,
            }
        }

    async def _ensure_graph(self):
        """Ensure graph is compiled (lazy async initialization)."""
        if self.graph is None:
            self.graph = await get_compiled_graph()

    async def run_with_message(
        self,
        message_text: str,
        user_id: str,
        conversation_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run graph with new message.

        Adds message to state and runs until interrupt or completion.

        Args:
            message_text: The user's message text
            user_id: Slack user ID of the sender
            conversation_context: Optional conversation history context dict
                containing messages, summary, and last_updated_at

        Returns:
            Result dict with:
            - action: "ask" | "preview" | "ready" | "review" | "discussion" | "hint" | "intro" | "nudge" | "continue" | "error"
            - questions: list[str] (if action=ask)
            - draft: TicketDraft (if action=preview)
            - message: str (if action=review/discussion/hint/intro/nudge)
            - error: str (if action=error)
        """
        from src.slack.session import get_session_lock
        lock = get_session_lock(self.identity.session_id)
        async with lock:
            try:
                # Get current state or initialize
                state = await self._get_current_state()

                # Add new message
                new_message = HumanMessage(
                    content=message_text,
                    id=f"{self.identity.thread_ts}:{datetime.utcnow().isoformat()}",
                )
                state["messages"] = state.get("messages", []) + [new_message]

                # Update session context
                state["thread_ts"] = self.identity.thread_ts
                state["channel_id"] = self.identity.channel_id
                state["user_id"] = user_id

                # Inject conversation context (Phase 11)
                if conversation_context is not None:
                    state["conversation_context"] = conversation_context

                # Run graph
                result_state = await self._run_until_interrupt(state)

                # Interpret result
                return self._interpret_result(result_state)

            except Exception as e:
                logger.error(f"Graph run failed: {e}", exc_info=True)
                return {"action": "error", "error": str(e)}

    async def _get_current_state(self) -> dict[str, Any]:
        """Get current state from checkpointer or initialize new."""
        await self._ensure_graph()
        try:
            checkpoint = await self.graph.aget_state(self._config)
            if checkpoint and checkpoint.values:
                return dict(checkpoint.values)
        except Exception as e:
            logger.debug(f"No existing state: {e}")

        # Initialize new state
        return {
            "messages": [],
            "draft": TicketDraft(epic_id=None),
            "phase": AgentPhase.COLLECTING,
            "step_count": 0,
            "thread_ts": self.identity.thread_ts,
            "channel_id": self.identity.channel_id,
            "user_id": None,
            "validation_report": {},
            "decision_result": {},
            # Question tracking (Phase 6)
            "pending_questions": None,
            "question_history": [],
            # First message tracking
            "is_first_message": True,
        }

    async def _run_until_interrupt(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run graph until interrupt point or completion.

        Interrupt points:
        - ASK: Need user input
        - PREVIEW: Show draft for approval
        - READY_TO_CREATE: Approved, ready for Jira (Phase 7)
        """
        # Stream through graph
        async for event in self.graph.astream(state, self._config):
            # Check for interrupt conditions
            current_state = event.get(list(event.keys())[0], {}) if event else {}

            decision_result = current_state.get("decision_result", {})
            action = decision_result.get("action")

            if action in ["ask", "preview", "ready_to_create", "review", "discussion", "hint", "ticket_action"]:
                # Interrupt - return current state
                logger.info(f"Graph interrupted at {action}")
                return self._merge_state(state, current_state)

        # Graph completed
        final_state = await self.graph.aget_state(self._config)
        return dict(final_state.values) if final_state else state

    def _merge_state(self, base: dict[str, Any], updates: dict) -> dict[str, Any]:
        """Merge state updates into base state."""
        result = dict(base)
        for key, value in updates.items():
            if value is not None:
                result[key] = value
        return result

    def _interpret_result(self, state: dict[str, Any]) -> dict[str, Any]:
        """Convert final state to action result."""
        decision_result = state.get("decision_result", {})
        action = decision_result.get("action", "continue")

        if action == "intro":
            return {
                "action": "intro",
                "message": decision_result.get("message", ""),
            }
        elif action == "nudge":
            return {
                "action": "nudge",
                "message": decision_result.get("message", ""),
            }
        elif action == "ask":
            return {
                "action": "ask",
                "questions": decision_result.get("questions", []),
                "reason": decision_result.get("reason", ""),
                "pending_questions": state.get("pending_questions"),
            }
        elif action == "preview":
            return {
                "action": "preview",
                "draft": state.get("draft"),
                "reason": decision_result.get("reason", ""),
                "potential_duplicates": decision_result.get("potential_duplicates", []),
            }
        elif action == "ready_to_create":
            return {
                "action": "ready",
                "draft": state.get("draft"),
            }
        elif action == "review":
            return {
                "action": "review",
                "message": decision_result.get("message", ""),
                "persona": decision_result.get("persona", ""),
                "topic": decision_result.get("topic", ""),
            }
        elif action == "discussion":
            return {
                "action": "discussion",
                "message": decision_result.get("message", ""),
            }
        elif action == "hint":
            return {
                "action": "hint",
                "message": decision_result.get("message", ""),
                "show_buttons": decision_result.get("show_buttons", False),
                "buttons": decision_result.get("buttons", []),
            }
        elif action == "ticket_action":
            return {
                "action": "ticket_action",
                "ticket_key": decision_result.get("ticket_key"),
                "action_type": decision_result.get("action_type"),
                "already_bound_to_same": decision_result.get("already_bound_to_same", False),
            }
        else:
            return {"action": "continue"}

    async def handle_approval(self, approved: bool) -> dict[str, Any]:
        """Handle user approval of preview.

        If approved, set phase to READY_TO_CREATE.
        If rejected, return to COLLECTING.
        """
        from src.slack.session import get_session_lock
        lock = get_session_lock(self.identity.session_id)
        async with lock:
            state = await self._get_current_state()

            if approved:
                state["phase"] = AgentPhase.READY_TO_CREATE
                # Save state
                await self.graph.aupdate_state(self._config, state)
                return {"action": "ready", "draft": state.get("draft")}
            else:
                state["phase"] = AgentPhase.COLLECTING
                await self.graph.aupdate_state(self._config, state)
                return {"action": "continue"}

    async def store_pending_questions(self, question_set_dict: dict[str, Any]) -> None:
        """Store QuestionSet when ask_user returns.

        Args:
            question_set_dict: QuestionSet as dict (serialized for state)
        """
        from src.slack.session import get_session_lock
        lock = get_session_lock(self.identity.session_id)
        async with lock:
            state = await self._get_current_state()
            state["pending_questions"] = question_set_dict
            await self.graph.aupdate_state(self._config, state)
            logger.debug(f"Stored pending questions: {question_set_dict.get('question_id')}")

    async def clear_pending_questions(self) -> dict[str, Any] | None:
        """Clear pending questions when user responds.

        Moves pending questions to question_history.

        Returns:
            The cleared QuestionSet dict, or None if no pending questions
        """
        from src.slack.session import get_session_lock
        lock = get_session_lock(self.identity.session_id)
        async with lock:
            state = await self._get_current_state()
            pending = state.get("pending_questions")

            if pending:
                # Move to history
                history = state.get("question_history", [])
                history.append(pending)
                state["question_history"] = history
                state["pending_questions"] = None

                await self.graph.aupdate_state(self._config, state)
                logger.debug(f"Cleared pending questions: {pending.get('question_id')}")
                return pending

            return None

    async def get_pending_questions(self) -> dict[str, Any] | None:
        """Get current pending questions.

        Returns:
            QuestionSet as dict, or None if no pending questions
        """
        state = await self._get_current_state()
        return state.get("pending_questions")

    async def _update_draft(self, draft: TicketDraft) -> None:
        """Update draft in current state.

        Used by modal handlers to update draft after user edits.

        Args:
            draft: Updated TicketDraft
        """
        try:
            state = await self._get_current_state()
            state["draft"] = draft
            await self.graph.aupdate_state(self._config, state)
            logger.debug(f"Updated draft version to {draft.version}")
        except Exception as e:
            logger.error(f"Failed to update draft: {e}", exc_info=True)

    async def _update_state(self, new_state: dict[str, Any]) -> None:
        """Update full state.

        Used for updating state fields like persona.

        Args:
            new_state: New state dictionary
        """
        await self._ensure_graph()
        try:
            await self.graph.aupdate_state(self._config, new_state)
            logger.debug("State updated")
        except Exception as e:
            logger.error(f"Failed to update state: {e}", exc_info=True)


# Session runner cache
_runners: dict[str, "GraphRunner"] = {}


def get_runner(identity: "SessionIdentity") -> GraphRunner:
    """Get or create runner for session."""
    if identity.session_id not in _runners:
        _runners[identity.session_id] = GraphRunner(identity)
    return _runners[identity.session_id]


def cleanup_runner(session_id: str) -> None:
    """Clean up runner when session ends."""
    if session_id in _runners:
        del _runners[session_id]
        logger.debug(f"Cleaned up runner for {session_id}")
