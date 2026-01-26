"""Sync handlers package.

Handles /maro sync command and sync-related button actions.

Re-exports all handlers for backward compatibility.
"""

from src.slack.handlers.sync.blocks import (
    build_sync_summary_blocks,
    build_conflict_detail_blocks,
    build_full_conflict_blocks,
)

from src.slack.handlers.sync.manual import (
    handle_maro_sync,
    handle_sync_command,
    handle_sync_track_all,
    handle_sync_track_selected,
    handle_sync_remove,
)

from src.slack.handlers.sync.conflict import (
    handle_sync_apply_all,
    handle_sync_use_slack,
    handle_sync_use_jira,
    handle_sync_skip,
    handle_sync_cancel,
    handle_sync_merge,
    handle_sync_merge_submit,
    handle_sync_track_all_button,
    handle_sync_remove_button,
    handle_sync_ignore_button,
    show_conflict_detail,
)

__all__ = [
    # Blocks module
    "build_sync_summary_blocks",
    "build_conflict_detail_blocks",
    "build_full_conflict_blocks",
    # Manual module
    "handle_maro_sync",
    "handle_sync_command",
    "handle_sync_track_all",
    "handle_sync_track_selected",
    "handle_sync_remove",
    # Conflict module
    "handle_sync_apply_all",
    "handle_sync_use_slack",
    "handle_sync_use_jira",
    "handle_sync_skip",
    "handle_sync_cancel",
    "handle_sync_merge",
    "handle_sync_merge_submit",
    "handle_sync_track_all_button",
    "handle_sync_remove_button",
    "handle_sync_ignore_button",
    "show_conflict_detail",
]
