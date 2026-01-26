"""Explain command handlers: /maro explain (OPS:EXPLAIN).

Handles explanation of MARO's last action/decision.
"""

import logging

from slack_sdk.web import WebClient

logger = logging.getLogger(__name__)


async def handle_explain_command(
    channel_id: str,
    team_id: str,
    user_id: str,
    thread_ts: str | None,
    client: WebClient,
    say,
):
    """Handle /maro explain - show explanation of last decisions.

    Gets current session state and formats an explanation of:
    - Last intent classification
    - Current draft status
    - Recent decision actions

    If no thread_ts, finds most recent active session in the channel.
    """
    from src.slack.session import SessionIdentity
    from src.graph.runner import get_runner, _runners

    # Find session - either from thread or most recent in channel
    identity = None

    if thread_ts:
        # Direct thread context
        identity = SessionIdentity(
            team_id=team_id or "default",
            channel_id=channel_id,
            thread_ts=thread_ts,
        )
        if identity.session_id not in _runners:
            identity = None

    # If no thread or session not found, look for any active session in this channel
    if identity is None:
        for session_id, runner in _runners.items():
            if runner.identity.channel_id == channel_id:
                identity = runner.identity
                break

    if identity is None:
        say(
            text="No active MARO sessions in this channel. Start a conversation by mentioning @MARO.",
            channel=channel_id,
        )
        return

    try:

        # Get runner and current state
        runner = get_runner(identity)
        state = await runner._get_current_state()

        # Build explanation
        parts = [":brain: *MARO Explain*\n"]

        # Intent info
        intent_result = state.get("intent_result", {})
        if intent_result:
            intent = intent_result.get("intent", "unknown")
            confidence = intent_result.get("confidence", 0)
            reasons = intent_result.get("reasons", [])
            parts.append(f"*Last Intent:* `{intent}` ({confidence:.0%} confidence)")
            if reasons:
                parts.append(f"_Reason: {reasons[0][:100]}_")

        # Draft info
        draft = state.get("draft")
        if draft:
            draft_title = draft.get("title", "Untitled") if isinstance(draft, dict) else getattr(draft, "title", "Untitled")
            draft_type = draft.get("issue_type", "Story") if isinstance(draft, dict) else getattr(draft, "issue_type", "Story")
            parts.append(f"\n*Current Draft:* {draft_type} - \"{draft_title[:50]}\"")

        # Decision info
        decision_result = state.get("decision_result", {})
        if decision_result:
            action = decision_result.get("action", "unknown")
            reason = decision_result.get("reason", "")
            parts.append(f"\n*Last Decision:* `{action}`")
            if reason:
                parts.append(f"_Reason: {reason[:100]}_")

        # Phase info
        phase = state.get("phase", "unknown")
        parts.append(f"\n*Phase:* `{phase}`")

        explanation = "\n".join(parts)

        # Post to the channel where command was run (with link to session thread)
        thread_link = f"<https://slack.com/archives/{identity.channel_id}/p{identity.thread_ts.replace('.', '')}|View thread>"
        explanation_with_link = explanation + f"\n\n{thread_link}"

        client.chat_postMessage(
            channel=channel_id,  # Post to command channel, not session channel
            text=explanation_with_link,
        )

        logger.info(
            "OPS:EXPLAIN completed",
            extra={
                "channel_id": channel_id,
                "user_id": user_id,
                "session_thread_ts": identity.thread_ts,
            }
        )

    except Exception as e:
        logger.error(f"Failed to run OPS:EXPLAIN: {e}", exc_info=True)
        say(
            text="Sorry, I couldn't explain my decisions right now. Please try again.",
            channel=channel_id,
        )
