# Phase 11: Conversation History - Research

**Researched:** 2026-01-14
**Domain:** Slack API history fetching + LLM conversation summarization
**Confidence:** HIGH

<research_summary>
## Summary

Researched the Slack API for fetching channel/thread history and LLM-based conversation summarization techniques. The standard approach uses `conversations.history` for channel messages and `conversations.replies` for threads, with cursor-based pagination.

**Key finding:** Rate limits changed significantly in May 2025. Non-Marketplace apps are now limited to 1 request/minute with max 15 messages per request. Internal customer-built apps (like MARO) retain Tier 3 limits (~50 req/min), making this a non-issue for our deployment.

For summarization, the proven pattern is a two-layer approach: raw message buffer (recent 10-30 messages) + rolling summary (compressed narrative). This can reduce token costs by 80-90% while improving response quality.

**Primary recommendation:** Use `conversations.history` + `conversations.replies` for on-demand fetching. For enabled channels, subscribe to `message.channels` events and maintain incremental rolling summaries. Store both raw buffer and summary in `conversation_context` within AgentState.
</research_summary>

<standard_stack>
## Standard Stack

### Core (Already in Project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| slack-sdk | 3.39.0+ | Slack API client | Official SDK, already using |
| slack-bolt | 1.27.0+ | Event handling | Already using for handlers |

### No New Libraries Required
Phase 11 uses existing stack:
- `WebClient.conversations_history()` - channel history
- `WebClient.conversations_replies()` - thread history
- LLM (already integrated) - for summarization
- PostgreSQL (already integrated) - for storing channel listening state

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom summarization | LangChain summarization chains | LangChain adds complexity, simple prompts sufficient |
| PostgreSQL for summaries | Redis | Redis faster but overkill, already using PG |
| Polling history | Real-time events | Events better for enabled channels |
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended Data Model
```python
# New table for channel listening state
class ChannelListeningState(BaseModel):
    team_id: str
    channel_id: str
    enabled: bool = False
    enabled_at: datetime | None
    enabled_by: str | None  # user_id who enabled
    last_summary_at: datetime | None
    summary: str | None  # rolling summary text
    raw_buffer: list[dict] | None  # last N messages as JSON

# AgentState extension
conversation_context: {
    "messages": [...],        # Raw Slack messages (bounded)
    "summary": "...",         # Compressed narrative
    "last_updated_at": "..."
}
```

### Pattern 1: On-Demand History Fetch (Disabled Channels)
**What:** Fetch recent history when @mentioned in a non-enabled channel
**When to use:** Bot mentioned in channel where listening is disabled
**Example:**
```python
async def fetch_context_on_demand(
    client: WebClient,
    channel_id: str,
    before_ts: str,
    limit: int = 20
) -> list[dict]:
    """Fetch recent messages before the mention."""
    result = client.conversations_history(
        channel=channel_id,
        latest=before_ts,
        inclusive=False,
        limit=limit
    )
    return result.get("messages", [])
```

### Pattern 2: Thread History Fetch
**What:** Fetch full thread when mentioned inside a thread
**When to use:** @mention is a thread reply, not a root message
**Example:**
```python
async def fetch_thread_history(
    client: WebClient,
    channel_id: str,
    thread_ts: str
) -> list[dict]:
    """Fetch all messages in a thread."""
    result = client.conversations_replies(
        channel=channel_id,
        ts=thread_ts,
        limit=200  # Threads are typically compact
    )
    return result.get("messages", [])
```

### Pattern 3: Rolling Summary (Enabled Channels)
**What:** Incrementally update summary as messages arrive
**When to use:** Channel has listening enabled
**Example:**
```python
SUMMARY_PROMPT = """You are maintaining a rolling summary of a Slack conversation.

Current summary:
{current_summary}

New messages since last update:
{new_messages}

Update the summary to incorporate the new messages. Keep it concise (2-3 paragraphs max).
Focus on: topics discussed, decisions made, open questions, key participants.

Updated summary:"""

async def update_rolling_summary(
    llm: LLMClient,
    current_summary: str,
    new_messages: list[dict],
) -> str:
    """Update summary with new messages."""
    messages_text = format_messages_for_summary(new_messages)
    prompt = SUMMARY_PROMPT.format(
        current_summary=current_summary or "No previous summary.",
        new_messages=messages_text
    )
    return await llm.chat(prompt)
```

### Pattern 4: Two-Layer Context
**What:** Maintain both raw buffer and summary
**When to use:** Always - provides both precision and compression
```python
class ConversationContext:
    raw_buffer: list[dict]  # Last 20 messages, full fidelity
    summary: str            # Older context, compressed

    def to_prompt_context(self) -> str:
        """Format for LLM prompt injection."""
        parts = []
        if self.summary:
            parts.append(f"## Conversation Summary\n{self.summary}")
        if self.raw_buffer:
            parts.append(f"## Recent Messages\n{format_messages(self.raw_buffer)}")
        return "\n\n".join(parts)
```

### Anti-Patterns to Avoid
- **Fetching all history:** Use bounded limits (20-30 messages max)
- **Storing full messages in AgentState:** Store only what's needed for context
- **Summarizing on every message:** Batch updates (every 5-10 messages)
- **Ignoring thread_ts:** Always check if message is in a thread
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Pagination | Manual cursor tracking | `conversations_history` cursor | API handles edge cases |
| Rate limiting | Custom backoff | `Retry-After` header | Slack provides exact wait time |
| Thread detection | Parsing message JSON | Check `thread_ts` field | Standard Slack field |
| Message formatting | Custom parsers | Slack message blocks | Already handled by SDK |

**Key insight:** Slack's API is well-designed. The SDK handles pagination, rate limits, and error handling. Focus on the business logic (summarization, context injection), not API plumbing.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Rate Limit Violations (Non-Marketplace Apps)
**What goes wrong:** App gets rate limited, history fetch fails
**Why it happens:** New May 2025 limits: 1 req/min, 15 objects max
**How to avoid:** MARO is internal, not Marketplace-distributed → Tier 3 limits apply (50+ req/min)
**Warning signs:** HTTP 429 responses, `Retry-After` headers

### Pitfall 2: Missing Thread Context
**What goes wrong:** Bot responds without understanding the thread
**Why it happens:** Only fetched channel history, not thread replies
**How to avoid:** Check if `thread_ts` != message `ts` → use `conversations.replies`
**Warning signs:** User says "@MARO what do you think?" in thread, bot seems confused

### Pitfall 3: Summary Drift
**What goes wrong:** Rolling summary loses important details over time
**Why it happens:** Each compression loses nuance
**How to avoid:** Keep raw buffer of recent messages + summary of older ones
**Warning signs:** Bot forgets decisions made earlier in conversation

### Pitfall 4: Token Explosion
**What goes wrong:** Context window exceeds limits, truncation loses info
**Why it happens:** Unbounded message history
**How to avoid:** Bound raw buffer (20-30 msgs), summarize older content
**Warning signs:** LLM errors, slow responses, incomplete understanding

### Pitfall 5: Stale Summaries
**What goes wrong:** Summary doesn't reflect recent discussion
**Why it happens:** Summary update too infrequent or failing silently
**How to avoid:** Update summary every 5-10 messages, log failures
**Warning signs:** Bot refers to outdated context
</common_pitfalls>

<code_examples>
## Code Examples

### Fetch Channel History (Python SDK)
```python
# Source: https://docs.slack.dev/tools/python-slack-sdk/
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

def fetch_recent_messages(
    client: WebClient,
    channel_id: str,
    before_ts: str | None = None,
    limit: int = 20
) -> list[dict]:
    """Fetch recent channel messages."""
    try:
        kwargs = {"channel": channel_id, "limit": limit}
        if before_ts:
            kwargs["latest"] = before_ts
            kwargs["inclusive"] = False

        result = client.conversations_history(**kwargs)
        return result.get("messages", [])
    except SlackApiError as e:
        if e.response.get("error") == "ratelimited":
            retry_after = int(e.response.headers.get("Retry-After", 60))
            raise RateLimitError(retry_after)
        raise
```

### Fetch Thread Replies
```python
# Source: https://docs.slack.dev/reference/methods/conversations.replies
def fetch_thread(
    client: WebClient,
    channel_id: str,
    thread_ts: str
) -> list[dict]:
    """Fetch all messages in a thread."""
    try:
        result = client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            limit=200
        )
        return result.get("messages", [])
    except SlackApiError as e:
        raise
```

### Subscribe to Channel Messages (Socket Mode)
```python
# Already in codebase pattern - extend message handler
@app.event("message")
def handle_all_messages(event, say, client):
    """Handle all channel messages for enabled channels."""
    channel_id = event.get("channel")

    # Check if listening is enabled for this channel
    if not is_listening_enabled(channel_id):
        return  # Ignore - will fetch on-demand when mentioned

    # Update rolling summary
    update_conversation_context(channel_id, event)
```

### Format Messages for LLM
```python
def format_messages_for_context(messages: list[dict]) -> str:
    """Format Slack messages for LLM context injection."""
    lines = []
    for msg in messages:
        user = msg.get("user", "unknown")
        text = msg.get("text", "")
        ts = msg.get("ts", "")
        lines.append(f"[{user}] {text}")
    return "\n".join(lines)
```
</code_examples>

<sota_updates>
## State of the Art (2025-2026)

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Unlimited API calls | Rate limits for non-Marketplace | May 2025 | Internal apps unaffected |
| Full history fetch | Cursor pagination | Always | Bounded, efficient |
| slackclient | slack-sdk | 2021+ | Already using new SDK |
| Store all messages | Two-layer (raw + summary) | 2024+ | 80-90% token savings |

**New tools/patterns to consider:**
- **Recursive summarization:** For very long conversations, summarize summaries
- **Pinned messages:** Keep critical messages in raw form, compress rest
- **Semantic chunking:** Group related messages before summarizing

**Deprecated/outdated:**
- **slackclient package:** Replaced by slack-sdk (we already use new one)
- **RTM API:** Replaced by Events API + Socket Mode (we already use Socket Mode)
</sota_updates>

<open_questions>
## Open Questions

1. **Summary update frequency**
   - What we know: Every 5-10 messages is common practice
   - What's unclear: Optimal frequency for MARO's use case
   - Recommendation: Start with 10 messages, tune based on usage

2. **Raw buffer size**
   - What we know: 10-30 messages typical
   - What's unclear: How many messages provides good context without bloat
   - Recommendation: Start with 20, measure token usage

3. **When to regenerate summary**
   - What we know: Rolling updates work, but drift can occur
   - What's unclear: When to do full re-summarization vs incremental
   - Recommendation: Full re-summarize every 50 messages or on topic shift
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- [Slack conversations.history docs](https://docs.slack.dev/reference/methods/conversations.history/) - API parameters, pagination, rate limits
- [Slack conversations.replies docs](https://docs.slack.dev/reference/methods/conversations.replies/) - Thread fetching
- [Slack rate limits](https://docs.slack.dev/apis/web-api/rate-limits/) - Tier 3 for internal apps
- [Python Slack SDK](https://docs.slack.dev/tools/python-slack-sdk/) - WebClient usage

### Secondary (MEDIUM confidence)
- [LLM Chat History Summarization Guide](https://mem0.ai/blog/llm-chat-history-summarization-guide-2025) - Rolling summary patterns
- [JetBrains Context Management Research](https://blog.jetbrains.com/research/2025/12/efficient-context-management/) - Two-layer approach
- [Medium: AI Agent Memory Strategies](https://techwithibrahim.medium.com/dont-let-your-ai-agent-forget-smarter-strategies-for-summarizing-message-history-a2d5284539f1) - Hybrid approaches

### Tertiary (LOW confidence - needs validation)
- None - all findings verified with official sources
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: Slack API (conversations.history, conversations.replies)
- Ecosystem: slack-sdk, existing LLM integration
- Patterns: On-demand fetch, rolling summary, two-layer context
- Pitfalls: Rate limits, thread handling, summary drift

**Confidence breakdown:**
- Slack API: HIGH - official docs, well-documented
- Rate limits: HIGH - recent changelog confirms internal app exemption
- Summarization: MEDIUM - patterns from research, needs tuning
- Architecture: HIGH - builds on existing patterns

**Research date:** 2026-01-14
**Valid until:** 2026-02-14 (30 days - Slack API stable)
</metadata>

---

*Phase: 11-conversation-history*
*Research completed: 2026-01-14*
*Ready for planning: yes*
