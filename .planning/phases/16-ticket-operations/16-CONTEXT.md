# Phase 16: Ticket Operations - Context

**Gathered:** 2026-01-15
**Status:** Ready for planning

<vision>
## How This Should Work

When user says "@Maro update SCRUM-111 with our architectural decisions" or "@Maro add comment to SCRUM-111", the bot should actually perform the operation instead of showing a stub message.

### The Problem

Current behavior (from Phase 13.1):
```
User: @Maro update SCRUM-111 with our architectural decisions
MARO: "I can help with update for SCRUM-111. (Full implementation coming soon)"
```

Phase 13.1 added TICKET_ACTION intent detection but left "update" and "add_comment" as stubs in handlers.py.

### Solution: Implement Ticket Operations

Add three operations to JiraService:
1. `update_issue()` - Update ticket fields
2. `add_comment()` - Add comment to ticket
3. `create_subtask()` - Create subtask under parent ticket

</vision>

<essential>
## What Must Be Nailed

1. **Update ticket** — Add/modify description, priority, status via Jira API
2. **Add comment** — Post comment to ticket with LLM-extracted content
3. **Create subtask** — Create subtask linked to parent ticket
4. **Handler dispatch** — Replace stubs with real API calls

</essential>

<specifics>
## Specific Ideas

### JiraService Extensions

Add methods to `src/jira/client.py`:

```python
async def update_issue(
    self,
    issue_key: str,
    updates: dict[str, Any],
    progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
) -> JiraIssue:
    """Update a Jira issue with field changes.

    Args:
        issue_key: Issue key (e.g., "SCRUM-111")
        updates: Fields to update (e.g., {"description": "...", "priority": "High"})
        progress_callback: Optional retry visibility callback

    Returns:
        Updated JiraIssue
    """
    payload = {"fields": updates}
    await self._request("PUT", f"/rest/api/3/issue/{issue_key}", json_data=payload, progress_callback=progress_callback)
    return await self.get_issue(issue_key)


async def add_comment(
    self,
    issue_key: str,
    comment: str,
    progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
) -> dict:
    """Add comment to a Jira issue.

    Args:
        issue_key: Issue key (e.g., "SCRUM-111")
        comment: Comment text
        progress_callback: Optional retry visibility callback

    Returns:
        Created comment response
    """
    payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": comment}]}]
        }
    }
    return await self._request("POST", f"/rest/api/3/issue/{issue_key}/comment", json_data=payload, progress_callback=progress_callback)


async def create_subtask(
    self,
    parent_key: str,
    summary: str,
    description: str = "",
    progress_callback: Optional[Callable[[str, int, int], Awaitable[None]]] = None,
) -> JiraIssue:
    """Create a subtask under parent issue.

    Args:
        parent_key: Parent issue key (e.g., "SCRUM-111")
        summary: Subtask summary
        description: Subtask description
        progress_callback: Optional retry visibility callback

    Returns:
        Created subtask JiraIssue
    """
    # Get parent project
    parent = await self.get_issue(parent_key)
    project_key = parent_key.split("-")[0]

    payload = {
        "fields": {
            "project": {"key": project_key},
            "parent": {"key": parent_key},
            "summary": summary,
            "issuetype": {"name": "Sub-task"},
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": description}]}]
            } if description else None
        }
    }
    # Remove None values
    payload["fields"] = {k: v for k, v in payload["fields"].items() if v is not None}

    response = await self._request("POST", "/rest/api/3/issue", json_data=payload, progress_callback=progress_callback)
    return await self.get_issue(response.get("key", ""))
```

### Handler Updates

Replace stubs in `src/slack/handlers.py` (lines ~514-520):

```python
elif action_type == "update":
    # Extract update content from conversation
    update_text = await _extract_update_content(result, state)
    jira_service = get_jira_service()
    await jira_service.update_issue(ticket_key, {"description": update_text})
    client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        text=f"Updated *{ticket_key}* with the latest context.",
    )

elif action_type == "add_comment":
    # Extract comment from conversation
    comment_text = await _extract_comment_content(result, state)
    jira_service = get_jira_service()
    await jira_service.add_comment(ticket_key, comment_text)
    client.chat_postMessage(
        channel=identity.channel_id,
        thread_ts=identity.thread_ts,
        text=f"Added comment to *{ticket_key}*.",
    )
```

### Content Extraction

Add LLM-based content extraction for updates and comments:

```python
UPDATE_EXTRACTION_PROMPT = '''Based on this conversation, extract what should be added to the Jira ticket.

Conversation context:
{conversation_context}

User request:
{user_message}

Return the content to add to the ticket description. Be concise and structured.
Use Jira formatting:
- h3. for headers
- * for bullet points
'''

COMMENT_EXTRACTION_PROMPT = '''Based on this conversation, extract the comment to add to the Jira ticket.

Conversation context:
{conversation_context}

User request:
{user_message}

Return a concise comment summarizing the key points.
'''
```

### Subtask Creation Flow

For "create subtasks for SCRUM-111", the flow is:
1. Intent detected as TICKET_ACTION with action_type="create_subtask"
2. Handler asks: "What subtasks should I create for SCRUM-111?"
3. User provides subtask list
4. Bot creates each subtask via API

</specifics>

<notes>
## Additional Context

### DoD (Definition of Done):

- [ ] `update_issue()` method in JiraService
- [ ] `add_comment()` method in JiraService
- [ ] `create_subtask()` method in JiraService
- [ ] Handler dispatches "update" action with real API call
- [ ] Handler dispatches "add_comment" action with real API call
- [ ] Content extraction prompts for update/comment
- [ ] Tests for new JiraService methods

### Integration Points:

- **Phase 13.1:** TICKET_ACTION intent already detected
- **Phase 14:** review_context can be used to populate update content
- **JiraService:** Already has retry/backoff, dry-run support

### Out of Scope:

- Batch subtask creation (create many at once)
- Status transitions (complex workflow rules)
- Field validation (Jira enforces this)

</notes>

---

*Phase: 16-ticket-operations*
*Context gathered: 2026-01-15*
