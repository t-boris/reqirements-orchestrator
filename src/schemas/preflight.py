"""Preflight check schemas for duplicate detection.

Implements Rule 6 & 7: Blocking duplicate detection with explicit user choices.
"""
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class DuplicateMatch(str, Enum):
    """Classification of duplicate match confidence.

    EXACT_MATCH: >85% confidence - blocks creation until user explicitly chooses
    LIKELY_DUPLICATE: 60-85% confidence - shows warning but allows creation
    NO_MATCH: <60% confidence - proceeds normally without duplicate UI
    """

    EXACT_MATCH = "exact_match"
    LIKELY_DUPLICATE = "likely_duplicate"
    NO_MATCH = "no_match"


class DuplicateCandidate(BaseModel):
    """A potential duplicate ticket found during preflight check."""

    key: str = Field(description="Jira issue key (e.g., SCRUM-123)")
    summary: str = Field(description="Issue summary/title")
    url: str = Field(description="URL to the Jira issue")
    status: str = Field(description="Current Jira status")
    assignee: Optional[str] = Field(default=None, description="Current assignee")
    updated: Optional[str] = Field(default=None, description="Last update timestamp")
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence score 0.0-1.0 that this is a duplicate",
    )
    match_reason: str = Field(
        default="",
        description="Explanation of why this matches the draft",
    )


class PreflightResult(BaseModel):
    """Result of preflight duplicate detection.

    Used to determine whether to block ticket creation and what UI to show.
    """

    match_state: DuplicateMatch = Field(
        default=DuplicateMatch.NO_MATCH,
        description="Classification of the best match",
    )
    duplicates: list[DuplicateCandidate] = Field(
        default_factory=list,
        description="List of potential duplicates found",
    )
    best_match: Optional[DuplicateCandidate] = Field(
        default=None,
        description="The highest confidence duplicate if any",
    )
    recommendation: Literal["link", "update", "create"] = Field(
        default="create",
        description="Recommended action based on match state",
    )

    @classmethod
    def from_search_results(
        cls,
        duplicates: list[dict],
        confidence_scores: list[float],
    ) -> "PreflightResult":
        """Create PreflightResult from search results with confidence scores.

        Args:
            duplicates: List of duplicate dicts with key, summary, url, status, etc.
            confidence_scores: Confidence score for each duplicate (0.0-1.0).

        Returns:
            PreflightResult with appropriate match_state based on confidence.
        """
        if not duplicates:
            return cls(
                match_state=DuplicateMatch.NO_MATCH,
                recommendation="create",
            )

        # Build candidates with confidence scores
        candidates = []
        for dup, conf in zip(duplicates, confidence_scores):
            candidates.append(
                DuplicateCandidate(
                    key=dup.get("key", ""),
                    summary=dup.get("summary", ""),
                    url=dup.get("url", ""),
                    status=dup.get("status", "Unknown"),
                    assignee=dup.get("assignee"),
                    updated=dup.get("updated"),
                    confidence=conf,
                    match_reason=dup.get("match_reason", ""),
                )
            )

        # Sort by confidence descending
        candidates.sort(key=lambda c: c.confidence, reverse=True)

        best_match = candidates[0] if candidates else None
        best_confidence = best_match.confidence if best_match else 0.0

        # Classify match state based on best confidence
        if best_confidence >= 0.85:
            match_state = DuplicateMatch.EXACT_MATCH
            recommendation = "link"
        elif best_confidence >= 0.60:
            match_state = DuplicateMatch.LIKELY_DUPLICATE
            recommendation = "link"
        else:
            match_state = DuplicateMatch.NO_MATCH
            recommendation = "create"

        return cls(
            match_state=match_state,
            duplicates=candidates,
            best_match=best_match,
            recommendation=recommendation,
        )

    def should_block_creation(self) -> bool:
        """Check if creation should be blocked pending user decision.

        Returns:
            True if EXACT_MATCH found (>85% confidence).
        """
        return self.match_state == DuplicateMatch.EXACT_MATCH

    def should_warn(self) -> bool:
        """Check if a warning should be shown but creation allowed.

        Returns:
            True if LIKELY_DUPLICATE found (60-85% confidence).
        """
        return self.match_state == DuplicateMatch.LIKELY_DUPLICATE
