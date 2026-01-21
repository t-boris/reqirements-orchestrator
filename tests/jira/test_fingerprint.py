"""Tests for description fingerprinting (Phase 23.4)."""
import pytest

from src.jira.fingerprint import (
    DescriptionSection,
    SectionFingerprint,
    DescriptionFingerprint,
    normalize_text,
    compute_hash,
    parse_sections,
    compute_fingerprint,
    fingerprint_to_dict,
    dict_to_fingerprint,
    find_changed_sections,
    detect_conflict,
)


class TestNormalizeText:
    """Test text normalization."""

    def test_strips_whitespace(self):
        """normalize_text strips leading/trailing whitespace."""
        assert normalize_text("  hello  ") == "hello"

    def test_collapses_multiple_spaces(self):
        """normalize_text collapses multiple spaces."""
        assert normalize_text("hello   world") == "hello world"

    def test_handles_newlines(self):
        """normalize_text collapses newlines."""
        assert normalize_text("hello\n\nworld") == "hello world"


class TestComputeHash:
    """Test hash computation."""

    def test_same_content_same_hash(self):
        """Identical content produces identical hash."""
        assert compute_hash("hello world") == compute_hash("hello world")

    def test_different_content_different_hash(self):
        """Different content produces different hash."""
        assert compute_hash("hello") != compute_hash("world")

    def test_normalized_content_matches(self):
        """Normalized content produces same hash."""
        assert compute_hash("hello  world") == compute_hash("hello world")


class TestParseSections:
    """Test section parsing."""

    def test_parses_markdown_sections(self):
        """parse_sections extracts markdown sections."""
        desc = """## Problem
This is the problem.

## Acceptance Criteria
- AC 1
- AC 2

## Architecture
Use a worker."""
        sections = parse_sections(desc)

        assert "problem" in sections
        assert "acceptance_criteria" in sections
        assert "architecture" in sections
        assert "AC 1" in sections["acceptance_criteria"]

    def test_default_to_problem(self):
        """Content without markers goes to problem section."""
        desc = "Just some text without markers."
        sections = parse_sections(desc)

        assert "problem" in sections
        assert "Just some text" in sections["problem"]

    def test_empty_description(self):
        """Empty description returns empty dict."""
        assert parse_sections("") == {}
        assert parse_sections(None) == {}


class TestComputeFingerprint:
    """Test fingerprint computation."""

    def test_computes_section_hashes(self):
        """compute_fingerprint creates per-section hashes."""
        desc = """## Problem
Problem text.

## Architecture
Architecture text."""
        fp = compute_fingerprint(desc)

        assert "problem" in fp.sections
        assert "architecture" in fp.sections
        assert fp.sections["problem"].hash is not None

    def test_computes_full_hash(self):
        """compute_fingerprint includes full document hash."""
        fp = compute_fingerprint("Some content")
        assert fp.full_hash is not None


class TestFingerprintSerialization:
    """Test fingerprint to/from dict conversion."""

    def test_roundtrip(self):
        """Fingerprint survives dict roundtrip."""
        original = compute_fingerprint("## Problem\nTest content.")
        as_dict = fingerprint_to_dict(original)
        restored = dict_to_fingerprint(as_dict)

        assert restored.full_hash == original.full_hash
        assert "problem" in restored.sections

    def test_none_input(self):
        """dict_to_fingerprint handles None."""
        assert dict_to_fingerprint(None) is None
        assert dict_to_fingerprint({}) is None


class TestFindChangedSections:
    """Test change detection."""

    def test_all_new_when_no_baseline(self):
        """All sections are 'changed' when no baseline."""
        new_fp = compute_fingerprint("## Problem\nNew content.")
        changed = find_changed_sections(None, new_fp)

        assert "problem" in changed

    def test_detects_changed_section(self):
        """Detects when a section changed."""
        old_fp = compute_fingerprint("## Problem\nOld content.")
        new_fp = compute_fingerprint("## Problem\nNew content.")

        changed = find_changed_sections(old_fp, new_fp)
        assert "problem" in changed

    def test_unchanged_not_reported(self):
        """Unchanged sections not in changed list."""
        old_fp = compute_fingerprint("## Problem\nSame content.")
        new_fp = compute_fingerprint("## Problem\nSame content.")

        changed = find_changed_sections(old_fp, new_fp)
        assert changed == []


class TestDetectConflict:
    """Test conflict detection."""

    def test_no_conflict_when_only_slack_changed(self):
        """No conflict if only Slack changed a section."""
        base = compute_fingerprint("## Problem\nOriginal.")
        slack = compute_fingerprint("## Problem\nSlack changed.")
        jira = compute_fingerprint("## Problem\nOriginal.")

        result = detect_conflict(slack, jira, base)
        assert result["conflicts"] == []
        assert result["auto_merge"].get("problem") == "slack"

    def test_no_conflict_when_only_jira_changed(self):
        """No conflict if only Jira changed a section."""
        base = compute_fingerprint("## Problem\nOriginal.")
        slack = compute_fingerprint("## Problem\nOriginal.")
        jira = compute_fingerprint("## Problem\nJira changed.")

        result = detect_conflict(slack, jira, base)
        assert result["conflicts"] == []
        assert result["auto_merge"].get("problem") == "jira"

    def test_conflict_when_both_changed(self):
        """Conflict when both sides changed same section."""
        base = compute_fingerprint("## Problem\nOriginal.")
        slack = compute_fingerprint("## Problem\nSlack changed.")
        jira = compute_fingerprint("## Problem\nJira changed.")

        result = detect_conflict(slack, jira, base)
        assert "problem" in result["conflicts"]

    def test_no_conflict_when_identical(self):
        """No conflict when all versions identical."""
        fp = compute_fingerprint("## Problem\nSame content.")
        result = detect_conflict(fp, fp, fp)

        assert result["conflicts"] == []
        assert result["auto_merge"] == {}
