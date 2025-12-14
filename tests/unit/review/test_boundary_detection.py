"""
Unit tests for boundary_detection module.

Tests boundary detection for bullets, numbered lists, lettered lists,
multi-line continuations, and edge cases.
"""

import pytest

from src.review.boundary_detection import (
    BoundaryDetector,
    TextBoundary,
    in_same_boundary,
)


class TestTextBoundary:
    """Test the TextBoundary dataclass."""

    def test_contains_position_inside(self):
        """Test that contains_position returns True for positions inside boundary."""
        boundary = TextBoundary(start=10, end=50, boundary_type="bullet", marker="•")
        assert boundary.contains_position(10)  # At start
        assert boundary.contains_position(30)  # In middle
        assert boundary.contains_position(49)  # Just before end

    def test_contains_position_outside(self):
        """Test that contains_position returns False for positions outside boundary."""
        boundary = TextBoundary(start=10, end=50, boundary_type="bullet", marker="•")
        assert not boundary.contains_position(9)  # Before start
        assert not boundary.contains_position(50)  # At end (exclusive)
        assert not boundary.contains_position(100)  # After end

    def test_repr(self):
        """Test string representation."""
        boundary = TextBoundary(start=10, end=50, boundary_type="bullet", marker="•")
        repr_str = repr(boundary)
        assert "bullet" in repr_str
        assert "10" in repr_str
        assert "50" in repr_str
        assert "•" in repr_str


class TestBoundaryDetector:
    """Test the BoundaryDetector class."""

    def test_empty_text(self):
        """Test that empty text returns no boundaries."""
        detector = BoundaryDetector()
        boundaries = detector.find_boundaries("")
        assert boundaries == []

    def test_single_unicode_bullet(self):
        """Test detection of single Unicode bullet point."""
        detector = BoundaryDetector()
        text = "• First bullet point"
        boundaries = detector.find_boundaries(text)

        assert len(boundaries) == 1
        assert boundaries[0].boundary_type == "bullet"
        assert boundaries[0].marker == "•"
        assert boundaries[0].start == 0
        assert boundaries[0].end == len(text)

    def test_multiple_unicode_bullets(self):
        """Test detection of multiple Unicode bullet points."""
        detector = BoundaryDetector()
        text = """• First bullet
• Second bullet
• Third bullet"""
        boundaries = detector.find_boundaries(text)

        assert len(boundaries) == 3
        assert all(b.boundary_type == "bullet" for b in boundaries)
        assert boundaries[0].marker == "•"
        assert boundaries[1].marker == "•"
        assert boundaries[2].marker == "•"

    def test_asterisk_bullet(self):
        """Test detection of asterisk bullet points."""
        detector = BoundaryDetector()
        text = """* First bullet
* Second bullet"""
        boundaries = detector.find_boundaries(text)

        assert len(boundaries) == 2
        assert all(b.boundary_type == "bullet" for b in boundaries)
        assert all(b.marker == "*" for b in boundaries)

    def test_hyphen_bullet(self):
        """Test detection of hyphen bullet points."""
        detector = BoundaryDetector()
        text = """- First bullet
- Second bullet"""
        boundaries = detector.find_boundaries(text)

        assert len(boundaries) == 2
        assert all(b.boundary_type == "bullet" for b in boundaries)
        assert all(b.marker == "-" for b in boundaries)

    def test_numbered_list(self):
        """Test detection of numbered list (1. 2. 3.)."""
        detector = BoundaryDetector()
        text = """1. First item
2. Second item
3. Third item"""
        boundaries = detector.find_boundaries(text)

        assert len(boundaries) == 3
        assert all(b.boundary_type == "numbered_list" for b in boundaries)
        assert boundaries[0].marker == "1."
        assert boundaries[1].marker == "2."
        assert boundaries[2].marker == "3."

    def test_lettered_list(self):
        """Test detection of lettered list (a. b. c.)."""
        detector = BoundaryDetector()
        text = """a. First item
b. Second item
c. Third item"""
        boundaries = detector.find_boundaries(text)

        assert len(boundaries) == 3
        assert all(b.boundary_type == "lettered_list" for b in boundaries)
        assert boundaries[0].marker == "a."
        assert boundaries[1].marker == "b."
        assert boundaries[2].marker == "c."

    def test_parenthetical_numbered_list(self):
        """Test detection of parenthetical numbered list (1) (2) (3)."""
        detector = BoundaryDetector()
        text = """(1) First item
(2) Second item
(3) Third item"""
        boundaries = detector.find_boundaries(text)

        assert len(boundaries) == 3
        assert all(b.boundary_type == "numbered_list" for b in boundaries)
        assert boundaries[0].marker == "(1)"
        assert boundaries[1].marker == "(2)"
        assert boundaries[2].marker == "(3)"

    def test_parenthetical_lettered_list(self):
        """Test detection of parenthetical lettered list (a) (b) (c)."""
        detector = BoundaryDetector()
        text = """(a) First item
(b) Second item
(c) Third item"""
        boundaries = detector.find_boundaries(text)

        assert len(boundaries) == 3
        assert all(b.boundary_type == "lettered_list" for b in boundaries)
        assert boundaries[0].marker == "(a)"
        assert boundaries[1].marker == "(b)"
        assert boundaries[2].marker == "(c)"

    def test_multi_line_bullet(self):
        """Test that multi-line bullets are grouped into single boundary."""
        detector = BoundaryDetector()
        text = """• First bullet that spans
  multiple lines with
  indented continuation"""
        boundaries = detector.find_boundaries(text)

        # Should be one boundary for the entire multi-line bullet
        assert len(boundaries) == 1
        assert boundaries[0].boundary_type == "bullet"
        assert boundaries[0].start == 0
        assert boundaries[0].end == len(text)

    def test_multi_line_bullets_with_blank_lines(self):
        """Test multi-line bullets with blank lines between continuations."""
        detector = BoundaryDetector()
        text = """• First bullet
  continues here

  and here
• Second bullet"""
        boundaries = detector.find_boundaries(text)

        # Should be two boundaries (blank lines are continuations)
        assert len(boundaries) == 2
        assert boundaries[0].boundary_type == "bullet"
        assert boundaries[1].boundary_type == "bullet"

    def test_mixed_boundary_types(self):
        """Test text with mixed bullet and numbered list."""
        detector = BoundaryDetector()
        text = """• Bullet point
1. Numbered item
• Another bullet"""
        boundaries = detector.find_boundaries(text)

        assert len(boundaries) == 3
        assert boundaries[0].boundary_type == "bullet"
        assert boundaries[1].boundary_type == "numbered_list"
        assert boundaries[2].boundary_type == "bullet"

    def test_indented_bullets(self):
        """Test bullets with leading whitespace."""
        detector = BoundaryDetector()
        text = """  • Indented bullet
  • Another indented bullet"""
        boundaries = detector.find_boundaries(text)

        assert len(boundaries) == 2
        assert all(b.boundary_type == "bullet" for b in boundaries)

    def test_plain_paragraphs_no_markers(self):
        """Test text without any bullet markers creates paragraph boundaries."""
        detector = BoundaryDetector()
        text = """This is a plain paragraph
with multiple lines
but no bullets"""
        boundaries = detector.find_boundaries(text)

        # Should create a single paragraph boundary
        assert len(boundaries) == 1
        assert boundaries[0].boundary_type == "paragraph"
        assert boundaries[0].start == 0
        assert boundaries[0].end == len(text)

    def test_get_boundary_at_position_found(self):
        """Test get_boundary_at_position returns correct boundary."""
        detector = BoundaryDetector()
        text = """• First bullet (0-14)
• Second bullet (15-31)"""
        boundaries = detector.find_boundaries(text)

        # Position in first bullet
        boundary = detector.get_boundary_at_position(5, boundaries)
        assert boundary is not None
        assert boundary == boundaries[0]

        # Position in second bullet (position 30 is in second line)
        boundary = detector.get_boundary_at_position(30, boundaries)
        assert boundary is not None
        assert boundary == boundaries[1]

    def test_get_boundary_at_position_not_found(self):
        """Test get_boundary_at_position returns None for out-of-range position."""
        detector = BoundaryDetector()
        text = "• Bullet"
        boundaries = detector.find_boundaries(text)

        # Position way beyond text
        boundary = detector.get_boundary_at_position(1000, boundaries)
        assert boundary is None

    def test_in_same_boundary_true(self):
        """Test in_same_boundary returns True for positions in same boundary."""
        text = """• First bullet
• Second bullet"""
        detector = BoundaryDetector()
        boundaries = detector.find_boundaries(text)

        # Both positions in first bullet
        assert in_same_boundary(0, 10, boundaries)

    def test_in_same_boundary_false(self):
        """Test in_same_boundary returns False for positions in different boundaries."""
        text = """• First bullet
• Second bullet"""
        detector = BoundaryDetector()
        boundaries = detector.find_boundaries(text)

        # Positions in different bullets
        assert not in_same_boundary(0, 20, boundaries)

    def test_in_same_boundary_out_of_range(self):
        """Test in_same_boundary returns False when one position is out of range."""
        text = "• Bullet"
        detector = BoundaryDetector()
        boundaries = detector.find_boundaries(text)

        # One position out of range
        assert not in_same_boundary(0, 1000, boundaries)

    def test_real_world_example_ltv_cac(self):
        """Test the real-world example from Issue 1 (LTV/CAC vs contribution margin)."""
        detector = BoundaryDetector()
        text = """• Six month LTV/CAC ratio for the years ended December 31, 2015, 2016 and 2017 cohorts
  was 1.42, 1.53 and 1.72, respectively; and
• Platform Order Contribution Margin for the years ended December 31, 2015, 2016 and 2017
  was 33.0%, 35.0% and 43.0%, respectively."""

        boundaries = detector.find_boundaries(text)

        # Should detect two bullet boundaries
        assert len(boundaries) == 2
        assert all(b.boundary_type == "bullet" for b in boundaries)

        # Position of "LTV/CAC" should be in first boundary
        ltv_pos = text.find("LTV/CAC")
        ltv_boundary = detector.get_boundary_at_position(ltv_pos, boundaries)
        assert ltv_boundary == boundaries[0]

        # Position of "33.0%" should be in second boundary
        value_pos = text.find("33.0%")
        value_boundary = detector.get_boundary_at_position(value_pos, boundaries)
        assert value_boundary == boundaries[1]

        # LTV/CAC and 33.0% should NOT be in same boundary
        assert not in_same_boundary(ltv_pos, value_pos, boundaries)
