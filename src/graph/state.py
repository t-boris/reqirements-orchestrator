"""Graph state models with clear channel/thread separation.

Implements the Git model for MARO:
- Channel = Repository (source of truth, owns registry)
- Thread = Working Tree (exploration/drafting space)
- Commit = Approved Decision (immutable truth entry)
- Jira = Remote (deployment target / replica)

This module provides separated state models that reflect this architecture.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional, TypedDict

from pydantic import BaseModel


class Phase(str, Enum):
    """Thread processing phase."""

    COLLECTING = "collecting"
    AWAITING_USER = "awaiting_user"
    APPROVED = "approved"
    REJECTED = "rejected"


class ChannelState(BaseModel):
    """Channel-level state (the repository).

    Represents persistent truth owned by the channel.
    This is the "repo" in Git model terms.
    """

    channel_id: str

    # Registry of work items (all types)
    workitem_ids: list[str] = []

    # Commit log (append-only)
    commit_ids: list[str] = []

    # Artifact references
    artifact_ids: list[str] = []

    # Channel settings
    mode: str = "collaborative"  # collaborative | managed
    jira_project: Optional[str] = None
    default_epic: Optional[str] = None

    # Activity tracking
    last_activity_at: Optional[datetime] = None
    active_threads: list[str] = []


class ThreadState(BaseModel):
    """Thread-level state (the working tree).

    Represents active exploration/drafting within a thread.
    This is the "working tree" in Git model terms.
    """

    thread_ts: str
    channel_id: str

    # Draft state (uncommitted changes)
    draft: Optional[dict] = None
    draft_type: Optional[str] = None  # epic, story, bug, task, spike

    # Interaction state
    pending_questions: list[dict] = []
    step_count: int = 0
    phase: Phase = Phase.COLLECTING
    reask_count: int = 0

    # Session tracking
    workflow_step: Optional[str] = None
    last_action: Optional[str] = None
    last_intent: Optional[str] = None
    last_decision: Optional[dict] = None

    # Binding (if thread is bound to a workitem)
    bound_workitem_id: Optional[str] = None


class AgentState(TypedDict, total=False):
    """Combined state passed through graph.

    This is the runtime state that flows through LangGraph nodes.
    It references both channel and thread state.
    """

    # Identity
    channel_id: str
    thread_ts: str
    user_id: str
    team_id: str

    # Input
    user_message: str
    event_id: str

    # Channel state reference
    channel_state: ChannelState

    # Thread state reference
    thread_state: ThreadState

    # Intent classification result
    intent: str
    intent_result: dict
    ops_subtype: str

    # Processing state
    draft: dict
    validation: dict
    decision: dict
    response: str
    action: str

    # Context
    channel_context: dict
    conversation_context: dict

    # Debug/operational
    recent_errors: list
    debug_collector: Any


def get_thread_phase(state: AgentState) -> Phase:
    """Get current phase from state (backward compatible).

    Supports both new nested access and old flat access.
    """
    if "thread_state" in state and state["thread_state"]:
        return state["thread_state"].phase
    return Phase(state.get("phase", "collecting"))


def get_draft(state: AgentState) -> Optional[dict]:
    """Get draft from state (backward compatible).

    Supports both new nested access and old flat access.
    """
    if "thread_state" in state and state["thread_state"]:
        return state["thread_state"].draft
    return state.get("draft")


def get_channel_id(state: AgentState) -> str:
    """Get channel_id from state (backward compatible).

    Supports both new nested access and old flat access.
    """
    if "channel_state" in state and state["channel_state"]:
        return state["channel_state"].channel_id
    return state.get("channel_id", "")


def get_thread_ts(state: AgentState) -> str:
    """Get thread_ts from state (backward compatible).

    Supports both new nested access and old flat access.
    """
    if "thread_state" in state and state["thread_state"]:
        return state["thread_state"].thread_ts
    return state.get("thread_ts", "")


def migrate_flat_to_separated(state: AgentState) -> AgentState:
    """Migrate flat state to separated state (backward compat).

    Use during transition period when some code still uses flat access.
    """
    # If already has separated state, return as-is
    if state.get("channel_state") and state.get("thread_state"):
        return state

    # Build channel state from flat fields
    channel_state = ChannelState(
        channel_id=state.get("channel_id", ""),
        jira_project=state.get("jira_project"),
        default_epic=state.get("default_epic"),
    )

    # Build thread state from flat fields
    thread_state = ThreadState(
        thread_ts=state.get("thread_ts", ""),
        channel_id=state.get("channel_id", ""),
        draft=state.get("draft"),
        pending_questions=state.get("pending_questions", []),
        step_count=state.get("step_count", 0),
        phase=Phase(state.get("phase", "collecting")),
        reask_count=state.get("reask_count", 0),
        workflow_step=state.get("workflow_step"),
        last_action=state.get("last_action"),
        last_intent=state.get("last_intent"),
    )

    state["channel_state"] = channel_state
    state["thread_state"] = thread_state
    return state


def flatten_separated_state(state: AgentState) -> AgentState:
    """Flatten separated state back to flat (backward compat).

    Use when passing to code that expects flat state.
    """
    if state.get("channel_state"):
        cs = state["channel_state"]
        state["jira_project"] = cs.jira_project
        state["default_epic"] = cs.default_epic

    if state.get("thread_state"):
        ts = state["thread_state"]
        state["draft"] = ts.draft
        state["pending_questions"] = ts.pending_questions
        state["step_count"] = ts.step_count
        state["phase"] = ts.phase.value
        state["reask_count"] = ts.reask_count
        state["workflow_step"] = ts.workflow_step
        state["last_action"] = ts.last_action
        state["last_intent"] = ts.last_intent

    return state
