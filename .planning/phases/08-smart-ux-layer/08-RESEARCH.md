# Phase 8: Smart UX Layer - Research

**Researched:** 2026-02-03
**Status:** Complete

## Research Areas

### 1. Slack Block Kit Patterns for Interactive Questions

**Key Findings:**

- **Actions block limits:** Max 25 elements per `actions` block, max 50 blocks per message
- **Button text:** Max 75 characters for button text, max 255 for `value` payload
- **Overflow menus:** Max 5 options - use for secondary actions
- **Message updates:** Use `chat.update` with same `ts` to replace buttons after selection (prevents double-clicks)
- **Modal vs inline:** Use inline buttons for quick choices (2-4 options); modals for complex forms (5+ fields)

**Recommended Patterns:**

```python
# Button-based question block
{
    "type": "actions",
    "block_id": "question_<uuid>",
    "elements": [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Option A"},
            "action_id": "answer_option_a",
            "value": json.dumps({"question_id": "q1", "answer": "option_a"}),
        },
        # ... more buttons
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "Something else"},
            "action_id": "answer_freeform",
            "value": json.dumps({"question_id": "q1", "answer": "freeform"}),
        },
    ],
}
```

**Progressive Disclosure:**
- Start with 2-4 most likely options as buttons
- Include "Something else" escape hatch on every button set
- After selection, update message to show chosen option (disable buttons)
- For 5+ options, use overflow menu or multi-step narrowing

**Post-Selection Update:**
```python
# After user clicks, update message to show selection
await client.chat_update(
    channel=channel_id,
    ts=message_ts,
    blocks=[
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Q:* {question}\n*A:* {selected_option}"}},
    ],
)
```

### 2. LLM Question Extraction (Structured Output)

**Approach: Extend Response Models with Follow-Up Questions**

Extend existing `ConverseLLMResponse` Pydantic model with optional `follow_up_questions` field. Uses existing `structured_completion()` infrastructure with zero client changes. Field descriptions act as prompt engineering.

**Schema Design:**

```python
class FollowUpOption(BaseModel):
    label: str = Field(description="Short button label, max 75 chars")
    description: str = Field(description="What this option means")

class FollowUpQuestion(BaseModel):
    question_text: str = Field(description="The question to ask the user")
    question_type: Literal["choice", "confirmation", "open_ended"] = Field(
        description="choice = buttons, confirmation = yes/no, open_ended = free text"
    )
    options: list[FollowUpOption] = Field(
        default_factory=list,
        description="Options for choice/confirmation types. Empty for open_ended."
    )
    priority: int = Field(
        default=0,
        description="Higher priority questions should be asked first"
    )

class ConverseLLMResponse(BaseModel):
    response_text: str = Field(description="The conversational response")
    follow_up_questions: list[FollowUpQuestion] = Field(
        default_factory=list,
        description="Questions to ask the user. Use 'choice' when there are 2-4 clear options. "
                    "Use 'confirmation' for yes/no. Use 'open_ended' only when no reasonable options exist."
    )
```

**Why this approach:**
- Zero new infrastructure - reuses `structured_completion()` + Instructor
- Field descriptions guide the LLM to generate button-friendly questions
- Graceful degradation: if `follow_up_questions` is empty, falls back to text response
- Type-driven rendering: `choice` → buttons, `confirmation` → Yes/No buttons, `open_ended` → no buttons

**Prompt Guidance (add to system prompt):**
```
When you have questions for the user:
- If there are 2-4 clear options, use question_type="choice" with options
- If it's a yes/no or confirm/deny, use question_type="confirmation"
- Only use question_type="open_ended" when no reasonable options can be predicted
- Keep option labels under 75 characters
- Always include the most likely option first
```

### 3. Intent Audit Logging

**Schema Design:**

```sql
CREATE TABLE intent_audit_log (
    id              BIGSERIAL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Message context
    channel_id      TEXT NOT NULL,
    thread_ts       TEXT,
    message_ts      TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    message_text    TEXT NOT NULL,

    -- PreGate stage
    pregate_result  TEXT,          -- PASS_THROUGH, BOT_MESSAGE, COMMAND, etc.
    pregate_data    JSONB,

    -- LLM classification stage
    raw_mode        TEXT,          -- Mode before threshold adjustment
    raw_confidence  FLOAT,
    classified_mode TEXT NOT NULL, -- Final mode after thresholds
    classified_confidence FLOAT NOT NULL,
    entity_type     TEXT,
    target_entity_id TEXT,
    entities_mentioned JSONB,
    reasoning       TEXT,

    -- Performance
    classification_ms INTEGER,

    PRIMARY KEY (id, created_at)
) PARTITION BY RANGE (created_at);

-- Monthly partitions, 90-day retention
CREATE TABLE intent_audit_log_2026_02 PARTITION OF intent_audit_log
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
```

**Key Design Decisions:**
- **Separate `raw_mode` vs `classified_mode`:** Enables tuning confidence thresholds without losing original LLM output
- **Append-only:** No updates, no deletes - pure audit trail
- **Monthly partitions:** Efficient retention management via `DROP TABLE` on old partitions
- **90-day retention:** Balance between debugging needs and storage costs
- **JSONB for flexible fields:** `pregate_data`, `entities_mentioned` can evolve without migrations

**Async Write Pattern:**

```python
import asyncio

_background_tasks: set[asyncio.Task] = set()  # Strong reference set

async def log_intent_audit(entry: IntentAuditEntry) -> None:
    """Fire-and-forget audit log write."""
    task = asyncio.create_task(_write_audit_entry(entry))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

async def _write_audit_entry(entry: IntentAuditEntry) -> None:
    try:
        async with get_pool().acquire() as conn:
            await conn.execute(INSERT_QUERY, *entry.to_row())
    except Exception as e:
        logger.warning(f"Failed to write audit log: {e}")
```

**Strong reference set** prevents garbage collection of fire-and-forget tasks. `add_done_callback` auto-cleans completed tasks.

**Query Patterns for `/maro inspect`:**

```sql
-- Why did the bot do X for this message?
SELECT * FROM intent_audit_log WHERE message_ts = $1;

-- Classification distribution over time
SELECT classified_mode, COUNT(*), AVG(classified_confidence)
FROM intent_audit_log
WHERE created_at > now() - interval '7 days'
GROUP BY classified_mode;

-- Threshold downgrades (tuning signal)
SELECT raw_mode, classified_mode, raw_confidence, reasoning
FROM intent_audit_log
WHERE raw_mode != classified_mode
ORDER BY created_at DESC LIMIT 50;
```

## Implementation Recommendations

1. **Start with LLM question extraction** (Phase 8.1) - Highest UX impact, extends existing models
2. **Add button rendering** (Phase 8.2) - Slack Block Kit patterns above
3. **Intent audit logging** (Phase 8.3) - Independent, can be developed in parallel
4. **Deterministic post-filters** (Phase 8.4) - Entity reference validation for MODIFY
5. **`/maro inspect` command** (Phase 8.5) - Requires audit log to be populated

## Quality Checklist

- [x] All research areas covered with implementation-ready detail
- [x] Slack API limits documented (25 elements, 50 blocks, 75 char buttons)
- [x] Pydantic schema designs provided for structured output
- [x] Database schema with partitioning and retention strategy
- [x] Async patterns for non-blocking audit writes
- [x] Progressive disclosure UX patterns documented
- [x] Query patterns for observability tooling

---

*Phase: 08-smart-ux-layer*
*Research completed: 2026-02-03*
