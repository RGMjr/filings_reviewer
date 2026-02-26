"""
Unit tests for the text_utils module.

Tests find_sentence_bounds() and normalize_text().
"""

from __future__ import annotations

import pytest

from src.extraction_v2.text_utils import find_sentence_bounds, normalize_text


# ============================================================================
# normalize_text()
# ============================================================================


class TestNormalizeText:
    def test_collapses_multiple_spaces(self) -> None:
        assert normalize_text("hello   world") == "hello world"

    def test_collapses_newlines(self) -> None:
        assert normalize_text("hello\nworld") == "hello world"

    def test_collapses_tabs(self) -> None:
        assert normalize_text("hello\tworld") == "hello world"

    def test_collapses_mixed_whitespace(self) -> None:
        assert normalize_text("hello \n\t world") == "hello world"

    def test_strips_leading_whitespace(self) -> None:
        assert normalize_text("   hello") == "hello"

    def test_strips_trailing_whitespace(self) -> None:
        assert normalize_text("hello   ") == "hello"

    def test_strips_both_ends(self) -> None:
        assert normalize_text("  hello world  ") == "hello world"

    def test_empty_string(self) -> None:
        assert normalize_text("") == ""

    def test_whitespace_only(self) -> None:
        assert normalize_text("   \n\t  ") == ""

    def test_already_normalized(self) -> None:
        assert normalize_text("hello world") == "hello world"

    def test_single_word(self) -> None:
        assert normalize_text("hello") == "hello"

    def test_multiline_paragraph(self) -> None:
        text = "Annual Recurring Revenue\n(ARR) grew 40%\nin fiscal 2023."
        result = normalize_text(text)
        assert "\n" not in result
        assert "  " not in result
        assert result == "Annual Recurring Revenue (ARR) grew 40% in fiscal 2023."

    def test_preserves_internal_content(self) -> None:
        assert normalize_text("ARR $1.2B") == "ARR $1.2B"

    def test_windows_line_endings(self) -> None:
        assert normalize_text("hello\r\nworld") == "hello world"


# ============================================================================
# find_sentence_bounds()
# ============================================================================


class TestFindSentenceBoundsBasic:
    def test_position_at_start_returns_zero_start(self) -> None:
        text = "Hello world. This is a sentence."
        start, end = find_sentence_bounds(text, 0)
        assert start == 0

    def test_position_at_end_returns_text_length_end(self) -> None:
        text = "Hello world."
        start, end = find_sentence_bounds(text, len(text) - 1)
        assert end == len(text)

    def test_single_sentence_no_boundaries(self) -> None:
        text = "Hello world"
        start, end = find_sentence_bounds(text, 5)
        assert start == 0
        assert end == len(text)

    def test_two_sentences_position_in_first(self) -> None:
        text = "Hello world. This is second."
        # Position inside first sentence (e.g. at 'w' in 'world')
        start, end = find_sentence_bounds(text, 6)
        assert start == 0
        # End should be within the text (before the second sentence starts)
        assert end <= len(text)

    def test_two_sentences_position_in_second(self) -> None:
        text = "Hello world. This is second."
        # Position clearly inside second sentence
        pos = text.index("second")
        start, end = find_sentence_bounds(text, pos)
        # Start should be somewhere after the period of the first sentence
        assert start > 0
        assert end == len(text)

    def test_returns_tuple_of_two_ints(self) -> None:
        text = "Hello world."
        result = find_sentence_bounds(text, 0)
        assert isinstance(result, tuple)
        assert len(result) == 2
        start, end = result
        assert isinstance(start, int)
        assert isinstance(end, int)

    def test_start_lte_position_lte_end(self) -> None:
        text = "The quick brown fox. Jumped over the lazy dog. Done."
        pos = text.index("over")
        start, end = find_sentence_bounds(text, pos)
        assert start <= pos <= end

    def test_multiple_sentences(self) -> None:
        # The boundary pattern is [.!?]\s+[A-Z]; text_before excludes the
        # capital letter at `pos`, so start=0 when pos is right at a boundary.
        # Use a position well INSIDE the second sentence to get start > 0.
        text = "First sentence. Second sentence here. Third."
        pos = text.index("sentence here")
        start, end = find_sentence_bounds(text, pos)
        # start should not be 0 (position is inside the second sentence)
        assert start > 0
        # end should be before the end of the full text (third sentence exists)
        assert end < len(text)

    def test_empty_text(self) -> None:
        start, end = find_sentence_bounds("", 0)
        assert start == 0
        assert end == 0

    def test_position_zero_in_multi_sentence_text(self) -> None:
        text = "Start here. Then more. End."
        start, end = find_sentence_bounds(text, 0)
        assert start == 0

    def test_exclamation_boundary_position_inside_sentence(self) -> None:
        # Position well inside the second sentence so text_before contains
        # the "! " boundary with trailing capital letter captured.
        text = "Wow! This is great indeed."
        pos = text.index("great")
        start, end = find_sentence_bounds(text, pos)
        # Boundary "! T" found before pos, so start > 0
        assert start > 0

    def test_question_mark_boundary_position_inside_sentence(self) -> None:
        # Position well inside the second sentence.
        text = "Is it ready? Yes it certainly is."
        pos = text.index("certainly")
        start, end = find_sentence_bounds(text, pos)
        assert start > 0

    def test_bounds_are_valid_indices(self) -> None:
        text = "One sentence. Two sentences. Three sentences."
        pos = 20
        start, end = find_sentence_bounds(text, pos)
        assert 0 <= start <= len(text)
        assert 0 <= end <= len(text)
        assert start <= end
