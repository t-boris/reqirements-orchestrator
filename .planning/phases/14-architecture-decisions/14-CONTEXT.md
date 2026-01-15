# Phase 14: Architecture Decision Records - Context

**Gathered:** 2026-01-15
**Status:** Ready for planning

<vision>
## How This Should Work

Из 13-CONTEXT.md (не реализовано):

> Когда человек говорит "let's go with this" после review:
> 1. MARO создаёт тред
> 2. Обсуждение продолжается в треде
> 3. Когда решение принято ("let's go with this") — MARO авто-детектит
> 4. Постит результат в канал: "📐 Architecture decision: [summary] (see thread)"

### Ключевая идея

> **Архитектура = процесс мышления (тред)**
> **Решение = состояние системы (канал)**

- Тред — это стол, на котором разложены чертежи
- Канал — это доска, где висят утверждённые решения

### Decision Detection

Фразы-триггеры для "решение принято":
- "let's go with this"
- "approved"
- "looks good, let's do it"
- "this is the approach"
- "agreed"
- "ship it"
- "I like option X, let's proceed"

### Channel Post Format

```
📐 *Architecture Decision*

*Topic:* User authentication for Access Portal
*Decision:* JWT-based auth with refresh tokens
*Thread:* [View discussion →](slack://thread_link)

_Decided by @user • Jan 15, 2026_
```

### Pinned Decisions

Опционально: пинить решения в канале для быстрого доступа.
Или добавлять в channel context (pins).

</vision>

<essential>
## What Must Be Nailed

1. **Decision detection** — Распознать когда решение принято (после review)
2. **Summary extraction** — Вычленить суть решения из треда
3. **Channel post** — Отформатировать и запостить в канал (не в тред)

</essential>

<specifics>
## Specific Ideas

### State Tracking

Добавить в AgentState:
```python
# Architecture decision tracking (Phase 14)
review_context: Optional[dict]  # Saved review for decision extraction
# Structure: {
#     "topic": str,
#     "review_summary": str,
#     "alternatives_discussed": list[str],
#     "review_timestamp": str
# }
```

### Decision Detection Patterns:
```python
DECISION_PATTERNS = [
    r"\blet'?s?\s+go\s+with\s+(?:this|that|option|approach)",
    r"\bapproved\b",
    r"\bagreed\b",
    r"\bship\s+it\b",
    r"\blooks?\s+good,?\s+let'?s?\s+(?:do|proceed)",
    r"\bthis\s+is\s+(?:the|our)\s+approach",
    r"\bI\s+(?:like|prefer)\s+(?:this|option)",
]
```

### Decision Extraction Prompt:
```
Based on this review thread, extract the architecture decision:

Review: {review_summary}
User's approval message: {approval_message}

Return:
- topic: What was being decided
- decision: The chosen approach (1-2 sentences)
- key_points: 2-3 bullet points of why this was chosen
```

### Channel Post:
```python
async def post_architecture_decision(
    client: WebClient,
    channel_id: str,
    thread_ts: str,
    topic: str,
    decision: str,
    user_id: str,
):
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"📐 *Architecture Decision*\n\n*Topic:* {topic}\n*Decision:* {decision}"
            }
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"<slack://channel?team=T&id={channel_id}&thread_ts={thread_ts}|View discussion> • Decided by <@{user_id}>"}
            ]
        }
    ]
    # Post to channel (not thread!)
    await client.chat_postMessage(channel=channel_id, blocks=blocks)
```

</specifics>

<notes>
## Additional Context

### DoD (Definition of Done):

- [ ] Decision detection after review (pattern matching)
- [ ] LLM extracts decision summary from review context
- [ ] Post formatted decision to channel (not thread)
- [ ] Include link back to thread discussion
- [ ] Logs: decision detected, topic, summary

### Integration Points:

- After ReviewFlow completes, save review_context to state
- On next message in thread, check for decision patterns
- If detected → extract → post to channel

### Out of Scope:

- Pinning decisions (nice-to-have)
- Decision versioning/updates
- Linking decisions to Jira tickets

</notes>

---

*Phase: 14-architecture-decisions*
*Context gathered: 2026-01-15*
