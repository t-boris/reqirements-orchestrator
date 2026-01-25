# 38-03 Summary: ContextSpec and ContextPacket Models

## What Was Implemented

Goal-driven context building models for the three-layer context architecture:

1. **ContextSpec** - Specification for what context to load
   - `mode`: SuperMode (BUILD, OPERATE, DECIDE, THINK, CHAT)
   - `target`: Target identifier (channel_id:thread_ts or workitem_id)
   - `purpose`: What the context is for
   - `budget_tokens`: Maximum tokens (500-16000)
   - `required_artifacts`: Artifacts that must be loaded
   - `include_history`: Whether to load conversation history
   - `history_limit`: Maximum messages to include
   - `include_attachments`: Whether to include attachment context
   - Factory methods: `for_extraction()`, `for_review()`, `for_ops_explain()`

2. **ContextPacket** - Structured context delivered to LLM
   - `header`: Mode and purpose header
   - `canonical`: Layer A (DB state - decisions, workitems, registry)
   - `history`: Layer B (conversation with rendered blocks)
   - `retrieved`: Layer C (attachments, Jira snapshots)
   - `total_tokens`: Estimated token count for budget tracking
   - Methods: `to_prompt()`, `to_compact_prompt()`, `is_empty`, `empty()`

## Files Created/Modified

| File | Action |
|------|--------|
| `src/context/spec.py` | Created - ContextSpec model |
| `src/context/packet.py` | Created - ContextPacket model |
| `src/context/__init__.py` | Modified - Added exports |

## Verification Results

```
python -m py_compile src/context/spec.py    # OK
python -m py_compile src/context/packet.py  # OK
from src.context import ContextSpec, ContextPacket  # OK
ContextSpec.for_extraction() creates valid spec  # OK
ContextPacket.to_prompt() formats sections correctly  # OK
```

## Commit Hashes

| Commit | Description |
|--------|-------------|
| `7afb44f` | feat(38-03): Add ContextSpec and ContextPacket models |
