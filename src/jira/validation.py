"""Jira validation operations - dry-run validation for batch creation.

Contains validation helpers for checking project access and required fields.
"""
import logging
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from src.jira.client import JiraService

from src.jira.exceptions import JiraAPIError

logger = logging.getLogger(__name__)


async def get_project(service: "JiraService", project_key: str) -> Optional[dict[str, Any]]:
    """Get project by key, or None if not found/no access.

    Args:
        service: JiraService instance
        project_key: Jira project key (e.g., "PROJ")

    Returns:
        Project dict with id, key, name, or None if not found
    """
    try:
        response = await service._request("GET", f"/rest/api/3/project/{project_key}")
        return response
    except JiraAPIError as e:
        if e.status_code == 404:
            return None
        raise


async def get_issue_types(service: "JiraService", project_key: str) -> list[dict[str, Any]]:
    """Get available issue types for a project.

    Args:
        service: JiraService instance
        project_key: Jira project key

    Returns:
        List of issue type dicts with id, name, subtask flag
    """
    response = await service._request(
        "GET",
        f"/rest/api/3/issue/createmeta/{project_key}/issuetypes",
    )
    return response.get("issueTypes", response.get("values", []))


async def get_required_fields(
    service: "JiraService", project_key: str, issue_type: str
) -> list[str]:
    """Get required fields for creating an issue type in a project.

    Args:
        service: JiraService instance
        project_key: Jira project key
        issue_type: Issue type name (e.g., "Epic", "Story")

    Returns:
        List of required field names
    """
    # First get issue type ID
    issue_types = await get_issue_types(service, project_key)
    issue_type_id = None
    for it in issue_types:
        if it.get("name") == issue_type:
            issue_type_id = it.get("id")
            break

    if not issue_type_id:
        return ["summary"]  # Default to just summary if type not found

    # Get fields for this issue type
    try:
        response = await service._request(
            "GET",
            f"/rest/api/3/issue/createmeta/{project_key}/issuetypes/{issue_type_id}",
        )
        fields = response.get("fields", response.get("values", []))
        required = []
        for field in fields:
            if isinstance(field, dict) and field.get("required"):
                required.append(field.get("fieldId") or field.get("key", ""))
        return required if required else ["summary"]
    except JiraAPIError:
        return ["summary"]  # Default on error


async def validate_issue_dry_run(
    service: "JiraService",
    project_key: str,
    issue_type: str,
    fields: dict,
) -> dict:
    """Validate issue creation without actually creating.

    Checks:
    - Project exists and user has access
    - Issue type valid for project
    - Required fields present
    - Field values valid

    Args:
        service: JiraService instance
        project_key: Jira project key (e.g., "PROJ")
        issue_type: Issue type name (e.g., "Epic", "Story")
        fields: Field values to validate (e.g., {"summary": "Title", "description": "..."})

    Returns:
        {"valid": True} or {"valid": False, "errors": [...]}
    """
    errors = []

    # Check project access
    project = await get_project(service, project_key)
    if not project:
        errors.append(f"Project {project_key} not found or no access")
        return {"valid": False, "errors": errors}

    # Check issue type valid
    valid_types = await get_issue_types(service, project_key)
    type_names = [t.get("name") for t in valid_types]
    if issue_type not in type_names:
        errors.append(
            f"Issue type '{issue_type}' not valid for project {project_key}. "
            f"Available types: {', '.join(type_names)}"
        )

    # Check required fields
    required = await get_required_fields(service, project_key, issue_type)
    for field in required:
        # Map common field names
        field_key = field
        if field == "summary":
            field_key = "summary"
        elif field == "description":
            field_key = "description"

        if field_key not in fields or not fields[field_key]:
            errors.append(f"Required field '{field}' is missing")

    if errors:
        return {"valid": False, "errors": errors}

    return {"valid": True}
