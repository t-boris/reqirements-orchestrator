# Phase 2: Slack Integration - Research

**Researched:** 2026-02-02
**Domain:** Slack Bolt Python SDK with FastAPI integration
**Confidence:** HIGH

<research_summary>
## Summary

Researched the Slack Bolt Python SDK ecosystem for building an async Slack bot with FastAPI. The standard approach uses `AsyncApp` from `slack-bolt` with the built-in FastAPI adapter. Socket Mode is available for development/firewalled environments but HTTP is recommended for production reliability.

Key finding: Slack Bolt has excellent built-in async support, rate limiting considerations, and a mature adapter system. The framework handles signature verification, event routing, and action acknowledgment automatically. Don't hand-roll any of these - use the framework.

**Primary recommendation:** Use `AsyncApp` + `AsyncSlackRequestHandler` + FastAPI. Follow the official examples exactly. Implement rate limiting wrapper for outbound API calls.

</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| slack-bolt | 1.27.0 | Bolt framework for Slack apps | Official SDK, async support, handles complexity |
| aiohttp | 3.x | Async HTTP client for Bolt | Required for AsyncApp API calls |
| slack-sdk | 3.x | Low-level Slack API client | Included with slack-bolt, provides WebClient |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| uvicorn | 0.24+ | ASGI server | Running FastAPI in production |
| python-dotenv | 1.x | Environment loading | Local development with .env files |

### Already in Project (from Phase 1)
| Library | Purpose |
|---------|---------|
| fastapi | Web framework - already chosen |
| pydantic | Validation - already in use |
| asyncpg | Async PostgreSQL - already in use |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| HTTP Mode | Socket Mode | Socket Mode for firewalled envs, HTTP for production reliability |
| FastAPI adapter | AIOHTTP built-in | FastAPI already chosen for project, adapter is official |
| slack-bolt | raw slack-sdk | Bolt handles all the boilerplate, no reason to go lower |

**Installation:**
```bash
pip install slack-bolt aiohttp
# Already have: fastapi, uvicorn, pydantic
```

</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended Project Structure
```
src/
├── slack/                    # Slack integration layer
│   ├── __init__.py
│   ├── app.py               # AsyncApp setup
│   ├── client.py            # SlackClient wrapper with rate limiting
│   ├── handlers/
│   │   ├── __init__.py
│   │   ├── events.py        # Message event handlers
│   │   ├── actions.py       # Button action handlers
│   │   └── commands.py      # Slash command handlers
│   ├── blocks/
│   │   ├── __init__.py
│   │   └── builders.py      # Block Kit message builders
│   └── middleware/
│       ├── __init__.py
│       └── logging.py       # Custom middleware
├── api/
│   └── routes/
│       └── slack.py         # FastAPI route mounting
```

### Pattern 1: AsyncApp with FastAPI
**What:** Mount Bolt AsyncApp as FastAPI endpoint
**When to use:** Always - this is the standard pattern
**Example:**
```python
# Source: https://github.com/slackapi/bolt-python/blob/main/examples/fastapi/async_app.py
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from fastapi import FastAPI, Request

# Create Bolt app
bolt_app = AsyncApp()
app_handler = AsyncSlackRequestHandler(bolt_app)

# Create FastAPI app
api = FastAPI()

@api.post("/slack/events")
async def slack_events(req: Request):
    return await app_handler.handle(req)
```

### Pattern 2: Action Handler with ack()
**What:** Handle button clicks with required acknowledgment
**When to use:** All interactive components (buttons, menus, etc.)
**Example:**
```python
# Source: https://docs.slack.dev/tools/bolt-python/concepts/actions/
@bolt_app.action("approve_button")
async def handle_approve(ack, body, client, say):
    # MUST ack first
    await ack()

    # Get action details
    user_id = body["user"]["id"]
    channel_id = body["channel"]["id"]
    action_value = body["actions"][0]["value"]

    # Respond
    await say(f"<@{user_id}> approved!")
```

### Pattern 3: Event Handler
**What:** Handle message events
**When to use:** Receiving messages, mentions, reactions
**Example:**
```python
@bolt_app.event("message")
async def handle_message(event, say, logger):
    # event contains: channel, user, text, ts, thread_ts, etc.
    logger.info(f"Message from {event['user']}: {event['text']}")

    # Don't respond to bot messages (avoid loops)
    if event.get("bot_id"):
        return

    # Respond in thread if message was in thread
    thread_ts = event.get("thread_ts", event["ts"])
    await say(text="Got your message!", thread_ts=thread_ts)

@bolt_app.event("app_mention")
async def handle_mention(event, say):
    await say(f"Hi <@{event['user']}>!")
```

### Pattern 4: Slash Command Handler
**What:** Handle /maro commands
**When to use:** Slash commands registered in Slack app settings
**Example:**
```python
@bolt_app.command("/maro")
async def handle_maro_command(ack, body, respond):
    await ack()  # Must ack within 3 seconds

    command_text = body.get("text", "").strip()
    user_id = body["user_id"]
    channel_id = body["channel_id"]

    # Parse subcommand
    parts = command_text.split()
    subcommand = parts[0] if parts else "help"

    # Respond ephemerally (only visible to user)
    await respond(
        text=f"Running /maro {subcommand}...",
        response_type="ephemeral"
    )
```

### Anti-Patterns to Avoid
- **Not calling ack() first:** Slack expects acknowledgment within 3 seconds. Always ack() before any processing.
- **Blocking in handlers:** All handlers must be async. Sync code blocks the event loop.
- **No rate limiting on outbound:** Slack has strict API limits. Always wrap client calls.
- **Hardcoded tokens:** Use environment variables, never commit tokens.

</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Request verification | Custom signature checking | Bolt's built-in verification | Crypto is error-prone, Bolt handles it |
| Event routing | Custom dispatchers | `@app.event()`, `@app.action()` | Framework handles all edge cases |
| Action acknowledgment | Manual responses | `ack()` utility | 3-second requirement, Bolt manages timing |
| Block Kit building | String concatenation | Dict structures or Block Kit Builder | Error-prone, hard to debug |
| Rate limiting | Custom token buckets | Wrap with simple semaphore | Slack provides Retry-After headers |
| OAuth flow | Custom OAuth | Bolt OAuth support | Complex redirect flow, state management |

**Key insight:** Slack Bolt exists specifically because building Slack apps from scratch is error-prone. The framework handles request verification, event routing, action acknowledgment timing, and error responses. Fighting it leads to subtle bugs like missed acknowledgments or signature verification failures.

</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Not Acknowledging Actions Fast Enough
**What goes wrong:** Slack shows "operation_timeout" error to user
**Why it happens:** ack() must be called within 3 seconds, but handler does work before ack()
**How to avoid:** Always `await ack()` as the FIRST line in action/command handlers
**Warning signs:** Users report buttons "don't work" intermittently

### Pitfall 2: Rate Limit Violations
**What goes wrong:** 429 errors, messages not sent
**Why it happens:** Posting too many messages (>1/sec to same channel)
**How to avoid:** Implement rate limiter wrapper, respect Retry-After header
**Warning signs:** "rate_limited" errors in logs, sporadic message delivery

### Pitfall 3: Event Loop Blocking
**What goes wrong:** Bot becomes unresponsive, handlers timeout
**Why it happens:** Sync code in async handlers (sync DB calls, blocking I/O)
**How to avoid:** All I/O must use async/await. Use `asyncpg` not `psycopg2`
**Warning signs:** High latency, timeouts, handlers taking >3 seconds

### Pitfall 4: Bot Responding to Itself
**What goes wrong:** Infinite message loop
**Why it happens:** Bot responds to messages, including its own
**How to avoid:** Check `event.get("bot_id")` and return early
**Warning signs:** Runaway message count, rate limits hit immediately

### Pitfall 5: Missing Thread Context
**What goes wrong:** Replies go to channel instead of thread
**Why it happens:** Not passing `thread_ts` when replying
**How to avoid:** Always check for and use `thread_ts` from incoming event
**Warning signs:** Conversations get confusing, context lost

</common_pitfalls>

<code_examples>
## Code Examples

### Complete AsyncApp Setup with FastAPI
```python
# Source: Slack Bolt docs + FastAPI example
import logging
from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from fastapi import FastAPI, Request

logging.basicConfig(level=logging.INFO)

# Bolt app reads SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET from env
bolt_app = AsyncApp()
handler = AsyncSlackRequestHandler(bolt_app)

# FastAPI app
api = FastAPI()

@api.post("/slack/events")
async def slack_events(req: Request):
    return await handler.handle(req)

@api.get("/health")
async def health():
    return {"status": "ok"}
```

### Rate-Limited Client Wrapper
```python
# Pattern for respecting Slack rate limits
import asyncio
from slack_sdk.web.async_client import AsyncWebClient

class RateLimitedClient:
    """Wrapper that respects Slack rate limits."""

    def __init__(self, client: AsyncWebClient, calls_per_second: float = 1.0):
        self.client = client
        self.semaphore = asyncio.Semaphore(1)
        self.min_interval = 1.0 / calls_per_second
        self.last_call = 0.0

    async def _rate_limit(self):
        async with self.semaphore:
            now = asyncio.get_event_loop().time()
            wait = self.min_interval - (now - self.last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self.last_call = asyncio.get_event_loop().time()

    async def chat_postMessage(self, **kwargs):
        await self._rate_limit()
        return await self.client.chat_postMessage(**kwargs)

    async def chat_update(self, **kwargs):
        await self._rate_limit()
        return await self.client.chat_update(**kwargs)
```

### Button Blocks Builder
```python
# Source: Slack Block Kit format
def build_approval_blocks(entity_id: str, title: str) -> list[dict]:
    """Build approval blocks with buttons."""
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{title}*"}
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": f"approve_{entity_id}",
                    "value": entity_id
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Object"},
                    "action_id": f"object_{entity_id}",
                    "value": entity_id
                }
            ]
        }
    ]
```

</code_examples>

<sota_updates>
## State of the Art (2025-2026)

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| RTM API | Events API + Socket Mode | 2020+ | RTM deprecated for new apps |
| Sync slack-bolt | AsyncApp | Always available | Async is standard for modern apps |
| HTTP only | Socket Mode option | Bolt 1.2.0 | Easier dev, but HTTP still recommended for prod |

**New considerations (2026):**
- **Rate limit changes (May 2025):** `conversations.history` and `conversations.replies` reduced to Tier 1 for non-Marketplace apps. Not relevant for this project (internal app).
- **Bolt 1.27.0:** Current stable, Python 3.7-3.14 support

**Deprecated/outdated:**
- **RTM API:** Don't use for new apps, replaced by Events API
- **Sync handlers in async app:** All middleware/listeners must be async in AsyncApp

</sota_updates>

<open_questions>
## Open Questions

1. **Socket Mode vs HTTP for this deployment**
   - What we know: HTTP recommended for production reliability, Socket Mode for firewalled envs
   - What's unclear: Deployment environment constraints
   - Recommendation: Use HTTP mode with FastAPI (already chosen). Socket Mode available if needed.

2. **Slash command registration**
   - What we know: `/maro` needs to be registered in Slack app settings
   - What's unclear: Already registered or needs setup?
   - Recommendation: Document registration steps in deployment guide

</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- [Slack Bolt Python - Async Docs](https://docs.slack.dev/tools/bolt-python/concepts/async/) - AsyncApp setup
- [Slack Bolt Python - Actions](https://docs.slack.dev/tools/bolt-python/concepts/actions/) - Button handling
- [slack-bolt PyPI](https://pypi.org/project/slack-bolt/) - Version 1.27.0 confirmed
- [GitHub Examples - FastAPI](https://github.com/slackapi/bolt-python/blob/main/examples/fastapi/async_app.py) - Official example

### Secondary (MEDIUM confidence)
- [Slack Rate Limits](https://docs.slack.dev/apis/web-api/rate-limits/) - Tier system verified
- [Socket Mode Docs](https://docs.slack.dev/tools/bolt-python/concepts/socket-mode/) - AsyncSocketModeHandler

### Tertiary (LOW confidence)
- None - all findings verified

</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: Slack Bolt Python (slack-bolt 1.27.0)
- Ecosystem: FastAPI adapter, aiohttp, slack-sdk
- Patterns: AsyncApp setup, action handlers, rate limiting
- Pitfalls: Acknowledgment timing, rate limits, event loops

**Confidence breakdown:**
- Standard stack: HIGH - official SDK, well-documented
- Architecture: HIGH - from official examples
- Pitfalls: HIGH - documented in official docs
- Code examples: HIGH - from official sources

**Research date:** 2026-02-02
**Valid until:** 2026-03-02 (30 days - stable ecosystem)

</metadata>

---

*Phase: 02-slack-integration*
*Research completed: 2026-02-02*
*Ready for planning: yes*
