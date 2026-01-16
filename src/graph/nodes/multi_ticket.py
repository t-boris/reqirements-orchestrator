"""Multi-ticket batch creation node with Epic linking.

Flow:
1. Dry-run validate all items
2. Create Epic first
3. Create stories linked to Epic (parent_link, not subtask)
4. Return created keys

From 20-CONTEXT.md v4: Stories are linked to Epic, not subtasks (configurable).
"""
import logging
from typing import Any

from src.config.settings import get_settings
from src.jira.client import JiraService
from src.schemas.state import AgentState

logger = logging.getLogger(__name__)


async def create_multi_ticket_batch(state: AgentState) -> dict[str, Any]:
    """Create all items in Jira with Epic linking.

    Flow:
    1. Dry-run validate all items
    2. Create Epic first
    3. Create stories linked to Epic (parent_link, not subtask)
    4. Return created keys

    Args:
        state: Agent state containing multi_ticket_state

    Returns:
        State update with created keys or validation error
    """
    multi_state = state.get("multi_ticket_state")
    if not multi_state:
        logger.error("No multi_ticket_state in state")
        return {
            "decision_result": {
                "action": "error",
                "message": "No multi-ticket state",
            }
        }

    items = multi_state.get("items", [])
    if not items:
        logger.error("No items in multi_ticket_state")
        return {
            "decision_result": {
                "action": "error",
                "message": "No items to create",
            }
        }

    settings = get_settings()
    jira = JiraService(settings)

    # Get project key from settings
    project_key = settings.jira_default_project
    if not project_key:
        logger.error("No jira_default_project configured")
        return {
            "decision_result": {
                "action": "error",
                "message": "No Jira project configured",
            }
        }

    try:
        # Step 1: Dry-run validate all items
        logger.info(
            "Validating multi-ticket batch",
            extra={"item_count": len(items), "project_key": project_key},
        )

        for item in items:
            issue_type = "Epic" if item["type"] == "epic" else "Story"
            fields = {
                "summary": item["title"],
                "description": item["description"],
            }

            validation = await jira.validate_issue_dry_run(project_key, issue_type, fields)
            if not validation.get("valid"):
                errors = validation.get("errors", [])
                logger.warning(
                    "Multi-ticket validation failed",
                    extra={
                        "item_id": item["id"],
                        "item_type": item["type"],
                        "errors": errors,
                    },
                )
                return {
                    "decision_result": {
                        "action": "validation_error",
                        "item_id": item["id"],
                        "item_title": item["title"],
                        "errors": errors,
                    },
                }

        logger.info("All items validated successfully")

        # Step 2: Create Epic first
        created_keys: list[str] = []
        epic_key: str | None = None

        for item in items:
            if item["type"] == "epic":
                logger.info(
                    "Creating Epic",
                    extra={"title": item["title"]},
                )
                # Use raw API call for Epic creation with Epic Name field
                payload = {
                    "fields": {
                        "project": {"key": project_key},
                        "summary": item["title"],
                        "description": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": item["description"]}],
                                }
                            ],
                        },
                        "issuetype": {"name": "Epic"},
                    }
                }

                # Dry-run handling
                if settings.jira_dry_run:
                    jira._mock_issue_counter += 1
                    epic_key = f"{project_key}-DRY{jira._mock_issue_counter}"
                    logger.info(f"Dry-run: would create Epic {epic_key}")
                else:
                    response = await jira._request("POST", "/rest/api/3/issue", json_data=payload)
                    epic_key = response.get("key")
                    logger.info(f"Created Epic: {epic_key}")

                created_keys.append(epic_key)
                break

        # Step 3: Create stories linked to Epic
        for item in items:
            if item["type"] == "story":
                logger.info(
                    "Creating Story linked to Epic",
                    extra={"title": item["title"], "epic_key": epic_key},
                )
                # Build story payload with parent link to Epic
                payload = {
                    "fields": {
                        "project": {"key": project_key},
                        "summary": item["title"],
                        "description": {
                            "type": "doc",
                            "version": 1,
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": item["description"]}],
                                }
                            ],
                        },
                        "issuetype": {"name": "Story"},
                    }
                }

                # Add parent Epic link if epic was created
                if epic_key:
                    payload["fields"]["parent"] = {"key": epic_key}

                # Dry-run handling
                if settings.jira_dry_run:
                    jira._mock_issue_counter += 1
                    story_key = f"{project_key}-DRY{jira._mock_issue_counter}"
                    logger.info(f"Dry-run: would create Story {story_key} linked to {epic_key}")
                else:
                    response = await jira._request("POST", "/rest/api/3/issue", json_data=payload)
                    story_key = response.get("key")
                    logger.info(f"Created Story: {story_key} linked to {epic_key}")

                created_keys.append(story_key)

        # Update state with created keys
        updated_multi_state = {**multi_state, "created_keys": created_keys}

        logger.info(
            "Multi-ticket batch created successfully",
            extra={
                "epic_key": epic_key,
                "story_count": len(created_keys) - 1 if epic_key else len(created_keys),
                "total_created": len(created_keys),
            },
        )

        return {
            "multi_ticket_state": updated_multi_state,
            "pending_action": None,
            "workflow_step": None,
            "decision_result": {
                "action": "multi_ticket_created",
                "keys": created_keys,
                "epic_key": epic_key,
            },
        }

    except Exception as e:
        logger.exception("Failed to create multi-ticket batch")
        return {
            "decision_result": {
                "action": "error",
                "message": f"Failed to create tickets: {str(e)}",
            },
        }
    finally:
        await jira.close()
