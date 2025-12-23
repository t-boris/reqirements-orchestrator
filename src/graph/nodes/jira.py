"""Jira integration nodes."""

import structlog
from langchain_core.prompts import ChatPromptTemplate

from src.graph.state import (
    HumanDecision,
    IntentType,
    RequirementState,
    WorkflowPhase,
)

from src.graph.nodes.common import (
    parse_llm_json_response,
    get_llm_for_state,
    logger,
    settings,
)

# =============================================================================
# Jira Write Node
# =============================================================================

async def jira_write_node(state: RequirementState) -> dict:
    """
    Create or update Jira issues via MCP.

    Creates a full hierarchy: Epic → Stories → Tasks.
    Uses parent_key to establish relationships.
    """
    from src.jira.mcp_client import get_jira_client

    action = state.get("jira_action")

    if not action:
        return {}

    # Get project key from channel config
    config = state.get("channel_config", {})
    project_key = config.get("jira_project_key", "MARO")

    logger.info(
        "writing_to_jira",
        channel_id=state.get("channel_id"),
        action=action,
        project_key=project_key,
    )

    try:
        jira = await get_jira_client()

        if action == "create":
            # Check if we have epics/stories/tasks from the workflow
            epics = state.get("epics", [])
            stories = state.get("stories", [])
            tasks = state.get("tasks", [])

            # If we have epics, create full hierarchy
            if epics:
                return await _create_jira_hierarchy(
                    jira, project_key, epics, stories, tasks
                )

            # Fallback: create single issue from draft
            draft = state.get("draft")
            if draft:
                return await _create_single_issue(jira, project_key, draft)

            return {}

        elif action == "update":
            issue_key = state.get("jira_issue_key")
            draft = state.get("draft")
            if issue_key and draft:
                result = await jira.update_issue(
                    issue_key=issue_key,
                    summary=draft.get("title"),
                    description=draft.get("description"),
                )
                return {"jira_issue_data": result}

    except Exception as e:
        logger.error("jira_write_failed", error=str(e))
        return {"error": f"Jira write failed: {str(e)}"}

    return {}


async def _create_single_issue(jira, project_key: str, draft: dict) -> dict:
    """Create a single Jira issue from a draft."""
    result = await jira.create_issue(
        project_key=project_key,
        issue_type=draft.get("issue_type", "Story"),
        summary=draft.get("title", ""),
        description=draft.get("description", ""),
        priority=draft.get("priority", "Medium"),
        labels=draft.get("labels", []),
    )

    issue_key = result.get("key")
    logger.info("jira_issue_created", key=issue_key)

    return {
        "jira_issue_key": issue_key,
        "jira_issue_data": result,
        "response": f"Created Jira issue: {issue_key}",
        "jira_items": [{"key": issue_key, "type": draft.get("issue_type", "Story")}],
    }


def _map_priority(priority: str) -> str:
    """Map workflow priority to Jira priority."""
    mapping = {
        # MoSCoW for stories
        "Must": "Highest",
        "Should": "High",
        "Could": "Medium",
        "Won't": "Low",
        # Standard for epics
        "critical": "Highest",
        "high": "High",
        "medium": "Medium",
        "low": "Low",
    }
    return mapping.get(priority, "Medium")


def _build_story_description(story: dict) -> str:
    """Build Jira description from user story format."""
    lines = []

    # User story format
    lines.append(f"*As a* {story.get('as_a', 'user')},")
    lines.append(f"*I want* {story.get('i_want', '...')},")
    lines.append(f"*So that* {story.get('so_that', '...')}.")
    lines.append("")

    # Acceptance criteria
    ac = story.get("acceptance_criteria", [])
    if ac:
        lines.append("*Acceptance Criteria:*")
        for criterion in ac:
            lines.append(f"* {criterion}")

    return "\n".join(lines)


def _build_task_description(task: dict) -> str:
    """Build Jira description from task format."""
    lines = []

    if task.get("description"):
        lines.append(task["description"])
        lines.append("")

    # Complexity
    if task.get("complexity"):
        lines.append(f"*Complexity:* {task['complexity']}")

    # Dependencies
    deps = task.get("dependencies", [])
    if deps:
        lines.append(f"*Dependencies:* Task indices {deps}")

    return "\n".join(lines)


async def _create_jira_hierarchy(
    jira,
    project_key: str,
    epics: list[dict],
    stories: list[dict],
    tasks: list[dict],
) -> dict:
    """
    Create full Jira hierarchy: Epic → Stories → Tasks.

    Returns created issue keys and summary.
    """
    created_items = []
    epic_keys = []
    story_keys = []
    errors = []

    # 1. Create Epics
    logger.info("creating_epics", count=len(epics))
    for i, epic in enumerate(epics):
        try:
            description = epic.get("description", "")
            if epic.get("objective"):
                description += f"\n\n*Objective:* {epic['objective']}"

            result = await jira.create_issue(
                project_key=project_key,
                issue_type="Epic",
                summary=epic.get("title", f"Epic {i + 1}"),
                description=description,
                priority=_map_priority(epic.get("priority", "medium")),
                labels=epic.get("labels", []),
            )

            epic_key = result.get("key")
            epic_keys.append(epic_key)
            created_items.append({
                "key": epic_key,
                "type": "Epic",
                "title": epic.get("title", ""),
            })
            logger.info("epic_created", key=epic_key, index=i)

        except Exception as e:
            error_msg = f"Epic {i} failed: {str(e)}"
            logger.error("epic_creation_failed", index=i, error=str(e))
            errors.append(error_msg)
            epic_keys.append(None)

    # 2. Create Stories (linked to Epics)
    logger.info("creating_stories", count=len(stories))
    for i, story in enumerate(stories):
        try:
            epic_index = story.get("epic_index", 0)
            parent_key = epic_keys[epic_index] if epic_index < len(epic_keys) else None

            description = _build_story_description(story)

            result = await jira.create_issue(
                project_key=project_key,
                issue_type="Story",
                summary=story.get("title", f"Story {i + 1}"),
                description=description,
                priority=_map_priority(story.get("priority", "Should")),
                labels=story.get("labels", []),
                parent_key=parent_key,  # Links to Epic
            )

            story_key = result.get("key")
            story_keys.append(story_key)
            created_items.append({
                "key": story_key,
                "type": "Story",
                "title": story.get("title", ""),
                "parent": parent_key,
            })
            logger.info("story_created", key=story_key, index=i, epic=parent_key)

        except Exception as e:
            error_msg = f"Story {i} failed: {str(e)}"
            logger.error("story_creation_failed", index=i, error=str(e))
            errors.append(error_msg)
            story_keys.append(None)

    # 3. Create Tasks (linked to Stories)
    logger.info("creating_tasks", count=len(tasks))
    for i, task in enumerate(tasks):
        try:
            story_index = task.get("story_index", 0)
            parent_key = story_keys[story_index] if story_index < len(story_keys) else None

            description = _build_task_description(task)

            result = await jira.create_issue(
                project_key=project_key,
                issue_type="Task",
                summary=task.get("title", f"Task {i + 1}"),
                description=description,
                priority="Medium",  # Tasks inherit story priority implicitly
                labels=task.get("labels", []),
                parent_key=parent_key,  # Links to Story
            )

            task_key = result.get("key")
            created_items.append({
                "key": task_key,
                "type": "Task",
                "title": task.get("title", ""),
                "parent": parent_key,
            })
            logger.info("task_created", key=task_key, index=i, story=parent_key)

        except Exception as e:
            error_msg = f"Task {i} failed: {str(e)}"
            logger.error("task_creation_failed", index=i, error=str(e))
            errors.append(error_msg)

    # Build summary response
    summary_lines = ["*Jira Issues Created:*"]
    summary_lines.append(f"• {len(epic_keys)} Epic(s): {', '.join(k for k in epic_keys if k)}")
    summary_lines.append(f"• {len(story_keys)} Story(ies): {', '.join(k for k in story_keys if k)}")
    task_keys = [item["key"] for item in created_items if item["type"] == "Task"]
    summary_lines.append(f"• {len(task_keys)} Task(s): {', '.join(task_keys)}")

    if errors:
        summary_lines.append(f"\n⚠️ {len(errors)} error(s) occurred during creation.")

    response = "\n".join(summary_lines)

    logger.info(
        "jira_hierarchy_created",
        epics=len(epic_keys),
        stories=len(story_keys),
        tasks=len(task_keys),
        errors=len(errors),
    )

    return {
        "jira_items": created_items,
        "jira_issue_key": epic_keys[0] if epic_keys else None,  # Primary key for reference
        "response": response,
        "error": "\n".join(errors) if errors else None,
    }


# =============================================================================
# Jira Command Handler Nodes
# =============================================================================


async def jira_read_node(state: RequirementState) -> dict:
    """
    Re-read/refresh a specific Jira issue.

    Fetches the latest data from Jira and updates memory.
    """
    from src.jira.mcp_client import get_jira_client

    target_key = state.get("jira_command_target")

    if not target_key:
        return {
            "response": "Please specify a Jira issue key to refresh (e.g., 're-read PROJ-123').",
            "error": "No target issue specified",
        }

    logger.info("jira_read_requested", key=target_key)

    try:
        jira = await get_jira_client()
        issue = await jira.get_issue(target_key)

        fields = issue.get("fields", {})
        status = fields.get("status", {}).get("name", "Unknown")
        summary = fields.get("summary", "")
        description = fields.get("description", "")[:500]
        issue_type = fields.get("issuetype", {}).get("name", "")

        # Build response
        response_lines = [
            f"*{target_key}* - {summary}",
            f"*Type:* {issue_type} | *Status:* {status}",
        ]
        if description:
            response_lines.append(f"\n_{description}_")

        logger.info("jira_read_complete", key=target_key, status=status)

        return {
            "response": "\n".join(response_lines),
            "jira_issue_data": issue,
        }

    except Exception as e:
        logger.error("jira_read_failed", key=target_key, error=str(e))
        return {
            "response": f"Failed to read {target_key}: {str(e)}",
            "error": str(e),
        }


async def jira_status_node(state: RequirementState) -> dict:
    """
    Show status of all Jira items in this thread/conversation.

    Displays current state of all tracked issues.
    """
    from src.jira.mcp_client import get_jira_client

    jira_items = state.get("jira_items", [])

    if not jira_items:
        return {
            "response": "No Jira items tracked in this conversation yet.\n\nCreate some requirements and I'll track them here!",
        }

    logger.info("jira_status_requested", item_count=len(jira_items))

    try:
        jira = await get_jira_client()

        # Fetch current status for each item
        status_lines = ["*Jira Items in This Thread:*\n"]
        status_emoji = {
            "To Do": "⚪",
            "In Progress": "🔵",
            "In Review": "🟡",
            "Done": "✅",
            "Blocked": "🔴",
        }

        for item in jira_items:
            key = item.get("key")
            if not key:
                continue

            try:
                issue = await jira.get_issue(key)
                fields = issue.get("fields", {})
                status = fields.get("status", {}).get("name", "Unknown")
                summary = fields.get("summary", item.get("title", ""))
                issue_type = item.get("type", "")

                emoji = status_emoji.get(status, "⚪")
                status_lines.append(f"{emoji} *{key}* [{issue_type}] - {summary}")
                status_lines.append(f"   Status: {status}")

            except Exception as e:
                status_lines.append(f"⚠️ *{key}* - Unable to fetch ({str(e)[:30]})")

        return {
            "response": "\n".join(status_lines),
        }

    except Exception as e:
        logger.error("jira_status_failed", error=str(e))
        return {
            "response": f"Failed to fetch status: {str(e)}",
            "error": str(e),
        }


async def jira_add_node(state: RequirementState) -> dict:
    """
    Add a new story/task to an existing epic.

    Uses LLM to generate the item based on user description,
    then creates it in Jira linked to the parent.
    """
    from src.jira.mcp_client import get_jira_client

    parent_key = state.get("jira_command_parent")
    item_type = state.get("jira_command_type", "story")
    message = state.get("message", "")

    if not parent_key:
        return {
            "response": "Please specify a parent issue to add to (e.g., 'add story to EPIC-123: user login feature').",
            "error": "No parent issue specified",
        }

    logger.info("jira_add_requested", parent=parent_key, type=item_type)

    # Get project key from config
    config = state.get("channel_config", {})
    project_key = config.get("jira_project_key", "MARO")

    try:
        jira = await get_jira_client()

        # Verify parent exists
        parent_issue = await jira.get_issue(parent_key)
        parent_summary = parent_issue.get("fields", {}).get("summary", "")

        # Use LLM to generate item details from the message
        llm = get_llm_for_state(state, temperature=0.3)

        prompt = f"""Generate a {item_type} to add to: {parent_key} - {parent_summary}

User's request: {message}

Respond in JSON:
{{
    "title": "<concise title>",
    "description": "<detailed description>",
    "acceptance_criteria": ["<criterion 1>", "<criterion 2>"]
}}
"""
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        result = parse_llm_json_response(response)

        title = result.get("title", "New item")
        description = result.get("description", "")
        ac = result.get("acceptance_criteria", [])

        # Build full description
        full_description = description
        if ac:
            full_description += "\n\n*Acceptance Criteria:*\n" + "\n".join(f"* {c}" for c in ac)

        # Create the issue
        issue_type_map = {"story": "Story", "task": "Task", "bug": "Bug"}
        jira_issue_type = issue_type_map.get(item_type.lower(), "Story")

        created = await jira.create_issue(
            project_key=project_key,
            issue_type=jira_issue_type,
            summary=title,
            description=full_description,
            parent_key=parent_key,
        )

        new_key = created.get("key")
        logger.info("jira_add_complete", key=new_key, parent=parent_key)

        # Update jira_items
        new_items = state.get("jira_items", []) + [{
            "key": new_key,
            "type": jira_issue_type,
            "title": title,
            "parent": parent_key,
        }]

        return {
            "response": f"Created *{new_key}*: {title}\n\nLinked to {parent_key}",
            "jira_items": new_items,
            "jira_issue_key": new_key,
        }

    except Exception as e:
        logger.error("jira_add_failed", parent=parent_key, error=str(e))
        return {
            "response": f"Failed to add {item_type} to {parent_key}: {str(e)}",
            "error": str(e),
        }


async def jira_update_node(state: RequirementState) -> dict:
    """
    Update a specific Jira issue based on user request.

    Uses LLM to determine what fields to update.
    """
    from src.jira.mcp_client import get_jira_client

    target_key = state.get("jira_command_target")
    message = state.get("message", "")

    if not target_key:
        return {
            "response": "Please specify a Jira issue to update (e.g., 'update PROJ-123 description to ...').",
            "error": "No target issue specified",
        }

    logger.info("jira_update_requested", key=target_key)

    try:
        jira = await get_jira_client()

        # Get current issue state
        current = await jira.get_issue(target_key)
        current_fields = current.get("fields", {})
        current_summary = current_fields.get("summary", "")
        current_description = current_fields.get("description", "")

        # Use LLM to determine updates
        llm = get_llm_for_state(state, temperature=0.3)

        prompt = f"""Analyze what the user wants to update in this Jira issue.

Issue: {target_key}
Current title: {current_summary}
Current description: {current_description[:500]}

User's request: {message}

Respond in JSON with ONLY the fields to update (omit fields that shouldn't change):
{{
    "summary": "<new title or null>",
    "description": "<new description or null>",
    "status": "<new status or null>"
}}
"""
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        result = parse_llm_json_response(response)

        # Extract updates (filter nulls and unchanged)
        updates = {}
        if result.get("summary") and result["summary"] != current_summary:
            updates["summary"] = result["summary"]
        if result.get("description") and result["description"] != current_description:
            updates["description"] = result["description"]

        if not updates:
            return {
                "response": f"No changes detected for {target_key}. Please be more specific about what you'd like to update.",
            }

        # Apply updates
        await jira.update_issue(
            issue_key=target_key,
            summary=updates.get("summary"),
            description=updates.get("description"),
            status=result.get("status"),
        )

        logger.info("jira_update_complete", key=target_key, updated_fields=list(updates.keys()))

        # Build response
        update_list = ", ".join(updates.keys())
        return {
            "response": f"Updated *{target_key}*\n\nChanged: {update_list}",
        }

    except Exception as e:
        logger.error("jira_update_failed", key=target_key, error=str(e))
        return {
            "response": f"Failed to update {target_key}: {str(e)}",
            "error": str(e),
        }


async def jira_delete_node(state: RequirementState) -> dict:
    """
    Delete a Jira issue.

    Requires confirmation before deletion (handled by checking for explicit intent).
    """
    from src.jira.mcp_client import get_jira_client

    target_key = state.get("jira_command_target")

    if not target_key:
        return {
            "response": "Please specify a Jira issue to delete (e.g., 'delete PROJ-123').",
            "error": "No target issue specified",
        }

    logger.info("jira_delete_requested", key=target_key)

    try:
        jira = await get_jira_client()

        # Get issue details before deletion for confirmation message
        issue = await jira.get_issue(target_key)
        summary = issue.get("fields", {}).get("summary", "")
        issue_type = issue.get("fields", {}).get("issuetype", {}).get("name", "")

        # Delete the issue
        await jira.delete_issue(target_key)

        logger.info("jira_delete_complete", key=target_key)

        # Remove from jira_items if present
        updated_items = [
            item for item in state.get("jira_items", [])
            if item.get("key") != target_key
        ]

        return {
            "response": f"Deleted *{target_key}* ({issue_type}): {summary}",
            "jira_items": updated_items,
        }

    except Exception as e:
        logger.error("jira_delete_failed", key=target_key, error=str(e))
        return {
            "response": f"Failed to delete {target_key}: {str(e)}",
            "error": str(e),
        }

