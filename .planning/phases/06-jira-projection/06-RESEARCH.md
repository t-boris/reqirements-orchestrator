# Phase 6: Jira Projection - Research

**Researched:** 2026-02-02
**Domain:** Jira Cloud REST API integration (Python)
**Confidence:** HIGH

<research_summary>
## Summary

Researched Python libraries and patterns for Jira Cloud integration. The standard approach uses `atlassian-python-api` (actively maintained, v4.0.7) with `asyncio.to_thread()` for async compatibility. Key consideration: Jira Cloud is transitioning to a points-based rate limiting model (enforced March 2, 2026) which affects how we design sync operations.

For description/comment fields, Jira Cloud v3 API uses Atlassian Document Format (ADF) - a JSON structure for rich text. The `atlas-doc-parser` library can convert between ADF and markdown. Authentication uses API tokens with basic auth for bot integrations (simpler than OAuth for server-side).

**Primary recommendation:** Use atlassian-python-api with asyncio.to_thread() wrapping. Implement exponential backoff for rate limits. Use ADF for rich text fields. Design sync to be idempotent and handle 429 responses gracefully.
</research_summary>

<standard_stack>
## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| atlassian-python-api | 4.0.7 | Jira API wrapper | Actively maintained, covers all Atlassian products, well-documented |
| atlas-doc-parser | 1.0.1 | ADF ↔ Markdown | Parses Jira's rich text format to/from readable formats |
| httpx | 0.27+ | Async HTTP (if needed) | Better async support than requests, for custom API calls |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tenacity | 8.2+ | Retry logic | Rate limit handling with exponential backoff |
| pydantic | 2.0+ | Data validation | Already in stack - use for Jira response models |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| atlassian-python-api | jira (pycontribs) | jira is Jira-only, better docs but less maintained |
| atlassian-python-api | aiojira | **Archived in 2019** - do not use |
| atlassian-python-api | Direct REST | More control but more work |

**Installation:**
```bash
pip install atlassian-python-api atlas-doc-parser tenacity
```
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended Project Structure
```
src/jira/
├── client.py           # JiraClient wrapper with async support
├── models.py           # JiraKey, JiraLink, SyncStatus types
├── sync_service.py     # JiraSyncService - main orchestration
├── preflight.py        # PreflightService - conflict detection
├── adf.py              # ADF conversion helpers
└── __init__.py         # Exports
```

### Pattern 1: Async Wrapper for Sync Library
**What:** atlassian-python-api is synchronous; wrap calls with asyncio.to_thread()
**When to use:** All Jira API calls from async context
**Example:**
```python
# Source: Python asyncio docs
import asyncio
from atlassian import Jira

class JiraClient:
    def __init__(self, url: str, email: str, token: str):
        self._jira = Jira(url=url, username=email, password=token)

    async def create_issue(self, project: str, summary: str, **fields) -> str:
        """Create issue asynchronously."""
        result = await asyncio.to_thread(
            self._jira.create_issue,
            fields={
                "project": {"key": project},
                "summary": summary,
                "issuetype": {"name": fields.get("issue_type", "Task")},
                **fields
            }
        )
        return result["key"]

    async def get_issue(self, key: str) -> dict:
        """Get issue by key."""
        return await asyncio.to_thread(self._jira.issue, key)
```

### Pattern 2: Rate Limit Handling with Tenacity
**What:** Exponential backoff with jitter for 429 responses
**When to use:** All API calls
**Example:**
```python
# Source: tenacity docs + Atlassian rate limit guidance
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type
)
from atlassian.errors import ApiError

class RateLimitError(Exception):
    """Raised when Jira returns 429."""
    pass

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=60),
    retry=retry_if_exception_type(RateLimitError),
)
async def call_with_retry(func, *args, **kwargs):
    """Call function with rate limit retry."""
    try:
        return await asyncio.to_thread(func, *args, **kwargs)
    except ApiError as e:
        if e.status_code == 429:
            raise RateLimitError(str(e))
        raise
```

### Pattern 3: ADF for Rich Text
**What:** Convert markdown to ADF for description fields
**When to use:** Creating/updating descriptions in Jira Cloud v3 API
**Example:**
```python
# Source: Atlassian ADF docs
def markdown_to_adf(text: str) -> dict:
    """Convert simple markdown to ADF."""
    # For simple text, create basic ADF structure
    return {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": text}
                ]
            }
        ]
    }

def create_managed_section(content: str) -> dict:
    """Create ADF with MARO managed section markers."""
    return {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "<!-- MARO:START -->"}
                ]
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": content}
                ]
            },
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "<!-- MARO:END -->"}
                ]
            }
        ]
    }
```

### Anti-Patterns to Avoid
- **Polling for changes:** Use webhooks or on-demand sync, not periodic polling
- **Creating sync client per-request:** Reuse single client instance (connection pooling)
- **Ignoring 429 responses:** Always implement backoff; points-based limits enforced March 2026
- **Using v2 API for Cloud:** v3 API has better ADF support and is the future
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| HTTP requests | Custom urllib/aiohttp | atlassian-python-api | Handles auth, sessions, error responses |
| Retry logic | Custom sleep loops | tenacity | Battle-tested, configurable, jitter built-in |
| ADF parsing | Custom JSON walker | atlas-doc-parser | ADF has many node types and edge cases |
| Custom field discovery | Hard-coded field IDs | `jira.fields()` method | Field IDs differ between Jira instances |
| Pagination | Manual offset tracking | Library's built-in pagination | JQL pagination changed (nextPageToken) |

**Key insight:** Jira's API has many quirks - custom field formats, ADF structure, pagination changes. Libraries encode years of edge case fixes.
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Custom Field ID Discovery
**What goes wrong:** Hard-coding `customfield_10001` fails across instances
**Why it happens:** Custom field IDs are instance-specific, not human-readable
**How to avoid:** Use `jira.fields()` to build name→ID mapping at startup
**Warning signs:** "Field not found" errors when deploying to different Jira instance

### Pitfall 2: Rate Limit Exhaustion
**What goes wrong:** Bulk operations trigger 429, no retry = lost updates
**Why it happens:** Not respecting points-based limits (65k points/hour)
**How to avoid:** Implement exponential backoff, check `X-RateLimit-Remaining` header
**Warning signs:** Intermittent failures during high-volume syncs

### Pitfall 3: ADF vs Wiki Markup Confusion
**What goes wrong:** Sending wiki markup to v3 API fails silently or corrupts formatting
**Why it happens:** v3 API expects ADF JSON, v2 expects wiki markup
**How to avoid:** Always use ADF for Jira Cloud, check API version
**Warning signs:** Description shows raw JSON or loses formatting

### Pitfall 4: Stale Token / Session Timeout
**What goes wrong:** Long-running processes fail with 401 after hours
**Why it happens:** API tokens have session timeouts
**How to avoid:** Handle 401 by recreating client; consider client refresh pattern
**Warning signs:** Failures that only happen after extended uptime

### Pitfall 5: Webhook Expiration
**What goes wrong:** Webhooks stop firing after 30 days
**Why it happens:** Jira expires webhooks that aren't refreshed
**How to avoid:** Implement webhook refresh endpoint; or use on-demand sync (our approach)
**Warning signs:** Webhook-based sync suddenly stops working
</common_pitfalls>

<code_examples>
## Code Examples

### Basic atlassian-python-api Usage
```python
# Source: atlassian-python-api docs
from atlassian import Jira

jira = Jira(
    url="https://your-instance.atlassian.net",
    username="email@example.com",
    password="api_token_here"  # API token, not password
)

# Create issue
result = jira.create_issue(fields={
    "project": {"key": "PROJ"},
    "summary": "Issue title",
    "description": "Description text",  # For v2 API
    "issuetype": {"name": "Story"}
})
print(result["key"])  # e.g., "PROJ-123"

# Search with JQL
issues = jira.jql("project = PROJ AND status = Open", limit=50)
for issue in issues["issues"]:
    print(issue["key"], issue["fields"]["summary"])

# Update issue
jira.update_issue_field("PROJ-123", {"summary": "New title"})

# Add comment
jira.issue_add_comment("PROJ-123", "This is a comment")
```

### Custom Field Handling
```python
# Source: Atlassian community best practices
def get_field_id_map(jira: Jira) -> dict[str, str]:
    """Build custom field name to ID mapping."""
    fields = jira.fields()
    return {f["name"]: f["id"] for f in fields}

# Usage
field_map = get_field_id_map(jira)
story_points_field = field_map.get("Story Points")  # e.g., "customfield_10016"

# Update custom field
jira.update_issue_field("PROJ-123", {
    story_points_field: 5
})
```

### Conflict Detection Pattern
```python
# Source: Spec maro_2_0.md
async def check_for_conflicts(
    jira: JiraClient,
    entity_key: str,
    local_version: int,
    fields_to_check: list[str]
) -> list[dict]:
    """Compare local entity with Jira issue."""
    issue = await jira.get_issue(entity_key)
    conflicts = []

    for field in fields_to_check:
        jira_value = issue["fields"].get(field)
        local_value = get_local_value(entity_key, field)

        if jira_value != local_value:
            conflicts.append({
                "field": field,
                "jira_value": jira_value,
                "local_value": local_value,
            })

    return conflicts
```
</code_examples>

<sota_updates>
## State of the Art (2025-2026)

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Count-based rate limits | Points-based rate limits | March 2, 2026 | Plan for points consumption, not request counts |
| Wiki markup (v2 API) | ADF JSON (v3 API) | Ongoing | Must convert markdown → ADF for Cloud |
| startAt pagination | nextPageToken pagination | 2025 | Use `enhanced_jql` for Jira Cloud |
| OAuth 1.0a | OAuth 2.0 (3LO) or API tokens | Deprecated | Use API tokens for bot integrations |

**New tools/patterns to consider:**
- **atlas-doc-parser:** New library for ADF ↔ Markdown conversion
- **Tiered rate limits:** Enterprise gets more points (up to 500k/hour)

**Deprecated/outdated:**
- **aiojira:** Archived in 2019, do not use
- **OAuth 1.0a:** Deprecated, use OAuth 2.0 or API tokens
- **Cookie-based auth:** Deprecated, use API tokens
</sota_updates>

<open_questions>
## Open Questions

1. **Webhook vs On-Demand**
   - What we know: User requested on-demand sync, webhooks have 30-day expiry
   - What's unclear: Future phases might benefit from webhooks for real-time
   - Recommendation: Build on-demand first, keep webhook support as Phase 7+ option

2. **ADF Complexity**
   - What we know: atlas-doc-parser handles parsing, but creating complex ADF is involved
   - What's unclear: How complex our descriptions need to be (tables? code blocks?)
   - Recommendation: Start with simple paragraph ADF, enhance if needed

3. **Multi-Jira Instance**
   - What we know: Each instance has different custom field IDs
   - What's unclear: Will MARO support multiple Jira instances?
   - Recommendation: Design field mapping to be per-channel configurable
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- [Atlassian Rate Limiting Docs](https://developer.atlassian.com/cloud/jira/platform/rate-limiting/) - Points system, headers, March 2026 enforcement
- [atlassian-python-api Docs](https://atlassian-python-api.readthedocs.io/jira.html) - API methods, usage patterns
- [ADF Structure Docs](https://developer.atlassian.com/cloud/jira/platform/apis/document/structure/) - JSON format for rich text
- [PyPI atlassian-python-api](https://pypi.org/project/atlassian-python-api/) - Version 4.0.7, Aug 2025

### Secondary (MEDIUM confidence)
- [Atlassian Community Forums](https://community.atlassian.com/) - Custom field handling patterns, verified with docs
- [GitHub aiojira](https://github.com/rominf/aiojira) - Confirmed archived Aug 2019

### Tertiary (LOW confidence - needs validation)
- atlas-doc-parser - New library, verify stability during implementation
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: Jira Cloud REST API v3
- Ecosystem: atlassian-python-api, atlas-doc-parser, tenacity
- Patterns: Async wrapping, rate limit handling, ADF conversion
- Pitfalls: Custom fields, rate limits, ADF confusion

**Confidence breakdown:**
- Standard stack: HIGH - atlassian-python-api is actively maintained, well-documented
- Architecture: HIGH - Patterns from official docs and production usage
- Pitfalls: HIGH - Documented in Atlassian forums, spec already identifies
- Code examples: HIGH - From official library docs

**Research date:** 2026-02-02
**Valid until:** 2026-03-02 (30 days - Jira API stable)
</metadata>

---

*Phase: 06-jira-projection*
*Research completed: 2026-02-02*
*Ready for planning: yes*
