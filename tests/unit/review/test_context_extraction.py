"""
Unit tests for context_extraction module.

Tests extracted from test_candidate_generator.py as part of P1.3 module splitting.
"""

import pytest

from src.review.context_extraction import ContextExtractor, DEFAULT_CONTEXT_WORDS


# =============================================================================
# ContextExtractor.extract_context Tests
# =============================================================================


class TestExtractContext:
    """Tests for context extraction."""

    @pytest.fixture
    def extractor(self):
        """Create a ContextExtractor with small context for testing."""
        return ContextExtractor(context_words=5)

    def test_context_around_position(self, extractor):
        """Extract context around a position."""
        text = "one two three four five TARGET six seven eight nine ten"
        position = text.index("TARGET")

        context = extractor.extract_context(text, position)
        assert "TARGET" in context
        # Should have some words before and after
        assert len(context.split()) >= 3

    def test_context_at_start(self, extractor):
        """Extract context when position is near start."""
        text = "TARGET one two three four five six seven eight nine ten"
        position = 0

        context = extractor.extract_context(text, position)
        assert "TARGET" in context

    def test_context_at_end(self, extractor):
        """Extract context when position is near end."""
        text = "one two three four five six seven eight nine TARGET"
        position = text.index("TARGET")

        context = extractor.extract_context(text, position)
        assert "TARGET" in context

    def test_whitespace_only_text(self, extractor):
        """Handle whitespace-only text gracefully."""
        text = "     \t\n   "
        context = extractor.extract_context(text, 0)

        # Should return the original text (no words to extract)
        assert context == text

    def test_empty_text(self, extractor):
        """Handle empty text gracefully."""
        text = ""
        context = extractor.extract_context(text, 0)

        assert context == ""

    def test_very_long_whitespace_text(self, extractor):
        """Long whitespace text should be truncated."""
        text = " " * 1000
        context = extractor.extract_context(text, 500)

        # Should return truncated version (max 500 chars)
        assert len(context) <= 500

    def test_uses_cached_words(self, extractor):
        """Should use cached words when provided."""
        text = "one two three four five TARGET six seven eight nine ten"
        position = text.index("TARGET")

        # Pre-compute word positions
        cached_words = extractor.parse_text_into_words(text)

        # Extract context using cache
        context = extractor.extract_context(text, position, cached_words=cached_words)
        assert "TARGET" in context
        assert len(context.split()) >= 3

    def test_extracts_correct_word_count(self, extractor):
        """Should extract approximately context_words words each direction."""
        # Create text with many words
        words = [f"word{i}" for i in range(100)]
        text = " ".join(words)
        target_word = "word50"
        position = text.index(target_word)

        context = extractor.extract_context(text, position)

        # Should have roughly (context_words * 2 + 1) words
        # context_words=5, so approximately 11 words
        context_word_count = len(context.split())
        assert 9 <= context_word_count <= 13  # Allow some variance


# =============================================================================
# ContextExtractor.parse_text_into_words Tests
# =============================================================================


class TestParseTextIntoWords:
    """Tests for parsing text into words."""

    @pytest.fixture
    def extractor(self):
        """Create a ContextExtractor."""
        return ContextExtractor()

    def test_parses_simple_text(self, extractor):
        """Parse simple text into words with positions."""
        text = "one two three"
        words = extractor.parse_text_into_words(text)

        assert len(words) == 3
        # Check positions are tuples with (start, end, word)
        assert all(len(w) == 3 for w in words)
        assert words[0][2] == "one"
        assert words[1][2] == "two"
        assert words[2][2] == "three"

    def test_captures_positions_correctly(self, extractor):
        """Word positions should match actual text positions."""
        text = "hello world"
        words = extractor.parse_text_into_words(text)

        assert len(words) == 2
        # "hello" at position 0-5
        assert words[0][0] == 0
        assert words[0][1] == 5
        assert text[words[0][0]:words[0][1]] == "hello"

        # "world" at position 6-11
        assert words[1][0] == 6
        assert words[1][1] == 11
        assert text[words[1][0]:words[1][1]] == "world"

    def test_handles_multiple_spaces(self, extractor):
        """Should treat multiple spaces as single separator."""
        text = "one    two     three"
        words = extractor.parse_text_into_words(text)

        assert len(words) == 3
        assert words[0][2] == "one"
        assert words[1][2] == "two"
        assert words[2][2] == "three"

    def test_handles_punctuation_as_words(self, extractor):
        """Punctuation should be treated as part of words."""
        text = "Hello, world!"
        words = extractor.parse_text_into_words(text)

        assert len(words) == 2
        assert words[0][2] == "Hello,"
        assert words[1][2] == "world!"

    def test_empty_text(self, extractor):
        """Should return empty list for empty text."""
        text = ""
        words = extractor.parse_text_into_words(text)

        assert words == []

    def test_whitespace_only(self, extractor):
        """Should return empty list for whitespace-only text."""
        text = "   \t\n  "
        words = extractor.parse_text_into_words(text)

        assert words == []


# =============================================================================
# Constants Tests
# =============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_default_context_words(self):
        """DEFAULT_CONTEXT_WORDS should be positive."""
        assert DEFAULT_CONTEXT_WORDS == 40
        assert DEFAULT_CONTEXT_WORDS > 0
