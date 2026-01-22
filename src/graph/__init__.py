"""LangGraph agent for PM-machine workflow.

Custom graph with extraction -> validation -> decision pipeline.
"""
from src.graph.graph import create_graph, get_compiled_graph
from src.graph.state import (
    ChannelState,
    ThreadState,
    Phase,
    AgentState,
    get_thread_phase,
    get_draft,
    get_channel_id,
    get_thread_ts,
    migrate_flat_to_separated,
    flatten_separated_state,
)

__all__ = [
    "create_graph",
    "get_compiled_graph",
    # Separated state models (Phase 25)
    "ChannelState",
    "ThreadState",
    "Phase",
    "AgentState",
    # Backward compat helpers
    "get_thread_phase",
    "get_draft",
    "get_channel_id",
    "get_thread_ts",
    "migrate_flat_to_separated",
    "flatten_separated_state",
]
