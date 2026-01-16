"""Tests for FactStore."""
import pytest
from src.db.fact_store import compute_canonical_id


class TestCanonicalId:
    """Tests for canonical ID computation."""

    def test_same_text_same_id(self):
        """Same text produces same ID."""
        id1 = compute_canonical_id("API uses OAuth2", "thread", "decision")
        id2 = compute_canonical_id("API uses OAuth2", "thread", "decision")
        assert id1 == id2

    def test_different_text_different_id(self):
        """Different text produces different ID."""
        id1 = compute_canonical_id("API uses OAuth2", "thread", "decision")
        id2 = compute_canonical_id("API uses JWT", "thread", "decision")
        assert id1 != id2

    def test_case_insensitive(self):
        """ID is case-insensitive."""
        id1 = compute_canonical_id("API Uses OAuth2", "thread", "decision")
        id2 = compute_canonical_id("api uses oauth2", "thread", "decision")
        assert id1 == id2

    def test_whitespace_normalized(self):
        """Whitespace is normalized."""
        id1 = compute_canonical_id("  API uses OAuth2  ", "thread", "decision")
        id2 = compute_canonical_id("API uses OAuth2", "thread", "decision")
        assert id1 == id2

    def test_different_scope_different_id(self):
        """Different scope produces different ID."""
        id1 = compute_canonical_id("API uses OAuth2", "thread", "decision")
        id2 = compute_canonical_id("API uses OAuth2", "channel", "decision")
        assert id1 != id2

    def test_different_type_different_id(self):
        """Different fact type produces different ID."""
        id1 = compute_canonical_id("API uses OAuth2", "thread", "decision")
        id2 = compute_canonical_id("API uses OAuth2", "thread", "constraint")
        assert id1 != id2

    def test_id_is_16_chars(self):
        """Canonical ID is truncated to 16 characters."""
        canonical_id = compute_canonical_id("Some fact text", "thread", "decision")
        assert len(canonical_id) == 16

    def test_id_is_hex(self):
        """Canonical ID is hexadecimal."""
        canonical_id = compute_canonical_id("Some fact text", "thread", "decision")
        # Should not raise ValueError if all chars are valid hex
        int(canonical_id, 16)
