# Phase 43: Task Progress UX

## Problem Statement

The "In Progress" indicator stays visible for too long and doesn't provide useful feedback. Users don't see what tasks are being worked on unless multiple tasks exist.

## Current Behavior

- In-progress spinner shows generic "Working..." or similar
- Task list only shown when multiple tasks exist
- Single-task operations show minimal feedback
- Long-running operations leave users uncertain about progress

## Proposed Changes

1. **Always show task list** — Even for single-task operations, display the task with its status
2. **Improve progress feedback** — Show what's actually being done, not just "working"
3. **Better timeout handling** — Show elapsed time or progress indicators for long operations
4. **Task-level status** — Show individual task progress, not just overall spinner

## User Story

> As a user, I want to see what MARO is working on at all times, so I understand the bot's progress and don't wonder if it's stuck.

## Requirements

- [ ] R1: Always display task list, even for single task
- [ ] R2: Show specific action being performed (not generic "working")
- [ ] R3: Add elapsed time indicator for long operations
- [ ] R4: Improve visual feedback for task state transitions

## Dependencies

- Phase 35: Multi-Intent Task Orchestration (TaskPlan foundation)
- Phase 36: Question Engine (status card patterns)
