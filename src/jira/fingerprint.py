"""Section-level fingerprinting for description sync (Phase 23.4).

Description is stored as structured blocks with fingerprints per section.
This enables detecting which specific sections changed for conflict resolution.

Sections:
- problem: Problem statement / user story
- acceptance_criteria: ACs / DoD
- architecture: Technical notes / decisions
- source: Thread links / provenance
- custom: Any additional sections

Fingerprint = hash of normalized section content.
Conflict = both sides changed same section since last sync.
"""
import hashlib
import re
from typing import Any

from pydantic import BaseModel, Field


class DescriptionSection(str):
    """Standard description section names."""

    PROBLEM = "problem"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    ARCHITECTURE = "architecture"
    SOURCE = "source"


# Section markers for parsing structured descriptions
SECTION_MARKERS = {
    DescriptionSection.PROBLEM: [
        "## Problem",
        "## User Story",
        "## Overview",
        "**Problem:**",
        "**User Story:**",
    ],
    DescriptionSection.ACCEPTANCE_CRITERIA: [
        "## Acceptance Criteria",
        "## AC",
        "## Definition of Done",
        "**Acceptance Criteria:**",
        "**AC:**",
    ],
    DescriptionSection.ARCHITECTURE: [
        "## Architecture",
        "## Technical Notes",
        "## Design",
        "**Architecture:**",
        "**Technical Notes:**",
    ],
    DescriptionSection.SOURCE: [
        "## Source",
        "## Links",
        "## References",
        "**Source:**",
        "---",  # Often used before source section
    ],
}


class SectionFingerprint(BaseModel):
    """Fingerprint for a single description section."""

    section: str = Field(description="Section name (e.g., 'problem', 'architecture')")
    hash: str = Field(description="SHA-256 hash of normalized content")
    char_count: int = Field(description="Character count for quick comparison")


class DescriptionFingerprint(BaseModel):
    """Complete fingerprint for a structured description."""

    sections: dict[str, SectionFingerprint] = Field(
        default_factory=dict,
        description="Fingerprints per section",
    )
    full_hash: str = Field(description="Hash of entire description")
    version: int = Field(default=1, description="Fingerprint schema version")


def normalize_text(text: str) -> str:
    """Normalize text for consistent hashing.

    Removes:
    - Leading/trailing whitespace
    - Multiple consecutive whitespace
    - Unicode variations (normalize to NFC)

    Args:
        text: Raw text to normalize

    Returns:
        Normalized text for hashing
    """
    import unicodedata

    # Normalize unicode
    text = unicodedata.normalize("NFC", text)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)

    # Strip
    text = text.strip()

    return text


def compute_hash(content: str) -> str:
    """Compute SHA-256 hash of normalized content.

    Args:
        content: Text to hash

    Returns:
        Hex digest of SHA-256 hash
    """
    normalized = normalize_text(content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def parse_sections(description: str) -> dict[str, str]:
    """Parse structured description into sections.

    Attempts to identify standard sections by markers.
    Unmatched content goes into 'problem' section.

    Args:
        description: Full description text

    Returns:
        Dict mapping section name to content
    """
    if not description:
        return {}

    sections: dict[str, str] = {}
    current_section = DescriptionSection.PROBLEM
    current_content: list[str] = []

    lines = description.split("\n")

    for line in lines:
        line_stripped = line.strip()

        # Check if this line marks a new section
        new_section = None
        for section_name, markers in SECTION_MARKERS.items():
            for marker in markers:
                if line_stripped.startswith(marker) or line_stripped == marker:
                    new_section = section_name
                    break
            if new_section:
                break

        if new_section and new_section != current_section:
            # Save current section
            if current_content:
                content = "\n".join(current_content).strip()
                if content:
                    sections[current_section] = content
            current_section = new_section
            current_content = []
            # Don't include the marker line itself
            continue

        current_content.append(line)

    # Save final section
    if current_content:
        content = "\n".join(current_content).strip()
        if content:
            sections[current_section] = content

    return sections


def compute_fingerprint(description: str) -> DescriptionFingerprint:
    """Compute fingerprint for a structured description.

    Args:
        description: Full description text

    Returns:
        DescriptionFingerprint with per-section hashes
    """
    sections = parse_sections(description)

    section_fingerprints = {}
    for section_name, content in sections.items():
        section_fingerprints[section_name] = SectionFingerprint(
            section=section_name,
            hash=compute_hash(content),
            char_count=len(content),
        )

    return DescriptionFingerprint(
        sections=section_fingerprints,
        full_hash=compute_hash(description),
        version=1,
    )


def fingerprint_to_dict(fp: DescriptionFingerprint) -> dict[str, str]:
    """Convert fingerprint to dict for storage in WorkItem.jira_fingerprint.

    Args:
        fp: DescriptionFingerprint model

    Returns:
        Dict mapping section name to hash string
    """
    result = {"_full": fp.full_hash, "_version": str(fp.version)}
    for section_name, section_fp in fp.sections.items():
        result[section_name] = section_fp.hash
    return result


def dict_to_fingerprint(data: dict[str, str]) -> DescriptionFingerprint | None:
    """Convert stored dict back to DescriptionFingerprint.

    Args:
        data: Dict from WorkItem.jira_fingerprint

    Returns:
        DescriptionFingerprint or None if invalid
    """
    if not data:
        return None

    full_hash = data.get("_full", "")
    version = int(data.get("_version", "1"))

    sections = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue
        sections[key] = SectionFingerprint(
            section=key,
            hash=value,
            char_count=0,  # Not stored, set to 0
        )

    return DescriptionFingerprint(
        sections=sections,
        full_hash=full_hash,
        version=version,
    )


def find_changed_sections(
    old_fp: DescriptionFingerprint | None,
    new_fp: DescriptionFingerprint,
) -> list[str]:
    """Find which sections changed between two fingerprints.

    Args:
        old_fp: Previous fingerprint (None for new item)
        new_fp: Current fingerprint

    Returns:
        List of section names that changed
    """
    if old_fp is None:
        return list(new_fp.sections.keys())

    changed = []

    # Check existing sections for changes
    all_sections = set(old_fp.sections.keys()) | set(new_fp.sections.keys())

    for section in all_sections:
        old_hash = old_fp.sections.get(section)
        new_hash = new_fp.sections.get(section)

        if old_hash is None or new_hash is None:
            # Section added or removed
            changed.append(section)
        elif old_hash.hash != new_hash.hash:
            # Content changed
            changed.append(section)

    return changed


def detect_conflict(
    slack_fp: DescriptionFingerprint,
    jira_fp: DescriptionFingerprint,
    base_fp: DescriptionFingerprint | None,
) -> dict[str, Any]:
    """Detect conflicts between Slack and Jira versions.

    Three-way merge logic:
    - If only Slack changed a section: no conflict, Slack wins
    - If only Jira changed a section: no conflict, Jira wins (hotfix)
    - If both changed same section: CONFLICT, manual resolution needed

    Args:
        slack_fp: Current Slack version fingerprint
        jira_fp: Current Jira version fingerprint
        base_fp: Last synced version fingerprint (common ancestor)

    Returns:
        Dict with 'conflicts' list and 'auto_merge' dict
    """
    conflicts = []
    auto_merge = {}  # section -> 'slack' | 'jira'

    if base_fp is None:
        # No common ancestor - everything is a potential conflict
        # Use full hash comparison
        if slack_fp.full_hash == jira_fp.full_hash:
            return {"conflicts": [], "auto_merge": {}}
        # Can't determine, report as conflict
        return {"conflicts": ["_full"], "auto_merge": {}}

    slack_changes = set(find_changed_sections(base_fp, slack_fp))
    jira_changes = set(find_changed_sections(base_fp, jira_fp))

    all_sections = slack_changes | jira_changes

    for section in all_sections:
        in_slack = section in slack_changes
        in_jira = section in jira_changes

        if in_slack and in_jira:
            # Both changed - conflict
            conflicts.append(section)
        elif in_slack:
            # Only Slack changed - auto-merge Slack version
            auto_merge[section] = "slack"
        elif in_jira:
            # Only Jira changed - auto-merge Jira version (hotfix)
            auto_merge[section] = "jira"

    return {"conflicts": conflicts, "auto_merge": auto_merge}
