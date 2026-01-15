"""Skill dispatcher - routes decisions to appropriate skills.

Formalizes the "Decision node decides when, skills handle how" pattern.
Decision node returns action (ask/preview/ready_to_create), dispatcher
handles the execution of that action via skills.
"""
import logging
from typing import Any, Optional, TYPE_CHECKING

from slack_sdk.web import WebClient
from slack_sdk.web.async_client import AsyncWebClient

from src.slack.session import SessionIdentity
from src.schemas.draft import TicketDraft
from src.graph.nodes.decision import DecisionResult

if TYPE_CHECKING:
    from src.slack.progress import ProgressTracker

logger = logging.getLogger(__name__)


class SkillDispatcher:
    """Routes decision results to appropriate skills.

    Pattern: Decision node decides "what" (ask/preview/ready), dispatcher handles "how".

    Usage:
        dispatcher = SkillDispatcher(client, identity)
        result = await dispatcher.dispatch(decision, draft)
        # result contains skill execution result
    """

    def __init__(
        self,
        client: WebClient | AsyncWebClient,
        identity: SessionIdentity,
        tracker: Optional["ProgressTracker"] = None,
    ):
        """Initialize dispatcher with Slack client and session identity.

        Args:
            client: Slack WebClient or AsyncWebClient for posting messages
            identity: Session identity (team:channel:thread_ts)
            tracker: Optional ProgressTracker for status updates
        """
        self.client = client
        self.identity = identity
        self.tracker = tracker

    async def dispatch(
        self,
        decision: DecisionResult,
        draft: TicketDraft,
    ) -> dict[str, Any]:
        """Dispatch decision to appropriate skill.

        Args:
            decision: DecisionResult from decision node
            draft: Current ticket draft

        Returns:
            Dict with:
            - action: The original action type
            - success: Whether skill execution succeeded
            - result: Skill-specific result data
            - error: Error message if failed
        """
        logger.info(
            f"Dispatching action: {decision.action}",
            extra={
                "session_id": self.identity.session_id,
                "reason": decision.reason,
            },
        )

        # Update progress tracker with skill-specific status
        if self.tracker:
            if decision.action == "preview":
                await self.tracker.set_operation("preparing_preview")
            elif decision.action == "ask":
                await self.tracker.set_operation("processing")
            elif decision.action == "ready_to_create":
                await self.tracker.set_operation("creating_ticket")

        if decision.action == "ask":
            return await self._dispatch_ask(decision)
        elif decision.action == "preview":
            logger.info(f"Dispatching preview with {len(decision.potential_duplicates)} duplicates")
            return await self._dispatch_preview(draft, decision.potential_duplicates)
        elif decision.action == "ready_to_create":
            return self._dispatch_ready(draft)
        else:
            logger.warning(f"Unknown action: {decision.action}")
            return {
                "action": decision.action,
                "success": False,
                "error": f"Unknown action: {decision.action}",
            }

    async def _dispatch_ask(self, decision: DecisionResult) -> dict[str, Any]:
        """Dispatch to ask_user skill.

        Posts questions to Slack thread and returns result.
        """
        from src.skills.ask_user import ask_user

        try:
            result = await ask_user(
                slack_client=self.client,
                channel=self.identity.channel_id,
                thread_ts=self.identity.thread_ts,
                questions=decision.questions,
                context="I need a bit more information:",
                is_reask=decision.is_reask,
                reask_count=decision.reask_count,
            )

            return {
                "action": "ask",
                "success": True,
                "result": {
                    "message_ts": result.message_ts,
                    "question_id": result.question_id,
                    "status": result.status.value,
                    "button_questions": result.button_questions,
                },
                "pending_questions": {
                    "question_id": result.question_id,
                    "questions": decision.questions,
                    "re_ask_count": decision.reask_count,
                    "message_ts": result.message_ts,
                },
            }
        except Exception as e:
            logger.error(f"ask_user skill failed: {e}", exc_info=True)
            return {
                "action": "ask",
                "success": False,
                "error": str(e),
            }

    async def _dispatch_preview(
        self,
        draft: TicketDraft,
        potential_duplicates: list[dict] = None,
    ) -> dict[str, Any]:
        """Dispatch to preview_ticket skill.

        Posts draft preview with approval buttons.
        """
        from src.skills.preview_ticket import preview_ticket

        try:
            result = await preview_ticket(
                client=self.client,
                channel=self.identity.channel_id,
                thread_ts=self.identity.thread_ts,
                draft=draft,
                session_id=self.identity.session_id,
                potential_duplicates=potential_duplicates,
            )

            return {
                "action": "preview",
                "success": True,
                "result": {
                    "message_ts": result.message_ts,
                    "preview_id": result.preview_id,
                    "draft_hash": result.draft_hash,
                    "status": result.status,
                },
                "draft": draft,
            }
        except Exception as e:
            logger.error(f"preview_ticket skill failed: {e}", exc_info=True)
            return {
                "action": "preview",
                "success": False,
                "error": str(e),
            }

    def _dispatch_ready(self, draft: TicketDraft) -> dict[str, Any]:
        """Handle ready_to_create action.

        No skill needed - just return the draft ready state.
        Actual Jira creation deferred to Phase 7.
        """
        return {
            "action": "ready",
            "success": True,
            "draft": draft,
            "result": {
                "status": "ready_to_create",
                "message": "Draft approved and ready to create in Jira",
            },
        }

    async def ask_user(self, questions: list[str], context: str = "") -> dict[str, Any]:
        """Direct skill call: ask user questions.

        Convenience method for calling ask_user skill directly without DecisionResult.

        Args:
            questions: List of questions to ask
            context: Optional context message

        Returns:
            Skill result dict
        """
        decision = DecisionResult(
            action="ask",
            questions=questions,
            reason=context or "Direct ask",
        )
        return await self._dispatch_ask(decision)

    async def preview_ticket(self, draft: TicketDraft) -> dict[str, Any]:
        """Direct skill call: preview ticket draft.

        Convenience method for calling preview_ticket skill directly.

        Args:
            draft: Ticket draft to preview

        Returns:
            Skill result dict
        """
        return await self._dispatch_preview(draft)
