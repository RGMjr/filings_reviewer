"""
Unit tests for boundary_detection module.

Tests boundary detection for bullets, numbered lists, lettered lists,
multi-line continuations, and edge cases.
"""


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


# =============================================================================
# P1.5: Sentence Boundary Detection Tests
# =============================================================================


class TestSentenceBoundaryDetection:
    """Test sentence boundary detection (P1.5 enhancement)."""

    # -------------------------------------------------------------------------
    # Basic Cases
    # -------------------------------------------------------------------------

    def test_empty_text(self):
        """Test that empty text returns no sentence boundaries."""
        detector = BoundaryDetector()
        sentences = detector.find_sentence_boundaries("")
        assert sentences == []

    def test_whitespace_only(self):
        """Test that whitespace-only text returns no sentence boundaries."""
        detector = BoundaryDetector()
        sentences = detector.find_sentence_boundaries("   \n  \t  ")
        assert sentences == []

    def test_single_sentence_with_period(self):
        """Test detection of a single sentence ending with period."""
        detector = BoundaryDetector()
        text = "Revenue grew 25%."
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 1
        assert sentences[0].boundary_type == "sentence"
        assert sentences[0].start == 0
        assert sentences[0].end == len(text)
        assert sentences[0].marker == "."

    def test_single_sentence_no_period(self):
        """Test detection of a single sentence without ending punctuation."""
        detector = BoundaryDetector()
        text = "Revenue grew 25%"
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 1
        assert sentences[0].boundary_type == "sentence"
        assert sentences[0].start == 0
        assert sentences[0].end == len(text)
        assert sentences[0].marker == ""  # No terminator

    def test_two_sentences(self):
        """Test detection of two sentences."""
        detector = BoundaryDetector()
        text = "Revenue grew 25%. Margin improved."
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 2
        assert all(s.boundary_type == "sentence" for s in sentences)
        # First sentence: "Revenue grew 25%."
        assert text[sentences[0].start : sentences[0].end] == "Revenue grew 25%."
        # Second sentence: "Margin improved."
        assert text[sentences[1].start : sentences[1].end] == "Margin improved."

    def test_three_sentences(self):
        """Test detection of three sentences."""
        detector = BoundaryDetector()
        text = "First sentence. Second sentence. Third sentence."
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 3

    # -------------------------------------------------------------------------
    # The Key Problem Example
    # -------------------------------------------------------------------------

    def test_problem_example_gross_margin_attrition(self):
        """Test THE KEY EXAMPLE from P1.5 requirements."""
        detector = BoundaryDetector()
        text = "Gross margin increased from 52.3% to 54.1% in 2023. Attrition declined from 35.1% to 34.2%."
        sentences = detector.find_sentence_boundaries(text)

        # Must be exactly 2 sentences
        assert len(sentences) == 2

        # Sentence 1: Contains "Gross margin" and "52.3%"
        sent1_text = text[sentences[0].start : sentences[0].end]
        assert "Gross margin" in sent1_text
        assert "52.3%" in sent1_text

        # Sentence 2: Contains "Attrition" and "35.1%"
        sent2_text = text[sentences[1].start : sentences[1].end]
        assert "Attrition" in sent2_text
        assert "35.1%" in sent2_text

        # Verify positions for keyword matching
        pos_gross_margin = text.find("Gross margin")
        pos_52_3 = text.find("52.3%")
        pos_attrition = text.find("Attrition")
        pos_35_1 = text.find("35.1%")

        # Gross margin and 52.3% in sentence 1
        assert sentences[0].contains_position(pos_gross_margin)
        assert sentences[0].contains_position(pos_52_3)

        # Attrition and 35.1% in sentence 2
        assert sentences[1].contains_position(pos_attrition)
        assert sentences[1].contains_position(pos_35_1)

        # Cross-sentence positions should NOT be in same sentence
        assert not sentences[0].contains_position(pos_attrition)
        assert not sentences[1].contains_position(pos_gross_margin)

    # -------------------------------------------------------------------------
    # Decimal Number Handling
    # -------------------------------------------------------------------------

    def test_decimal_not_sentence_boundary(self):
        """Test that decimals like 52.3% don't trigger false sentence breaks."""
        detector = BoundaryDetector()
        text = "Margin was 52.3% in Q1."
        sentences = detector.find_sentence_boundaries(text)

        # Should be exactly 1 sentence (52.3 is NOT a sentence end)
        assert len(sentences) == 1

    def test_multiple_decimals_single_sentence(self):
        """Test sentence with multiple decimal numbers."""
        detector = BoundaryDetector()
        text = "Growth ranged from 1.5% to 2.3% in fiscal 2023."
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 1

    def test_currency_decimals(self):
        """Test that currency values like $1.5M don't trigger false breaks."""
        detector = BoundaryDetector()
        text = "Revenue was $1.5M in Q1. Expenses were $1.2M."
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 2

    def test_year_ending_sentence(self):
        """Test that years at end of sentence (2023.) are detected correctly."""
        detector = BoundaryDetector()
        text = "This happened in 2023. The next year saw growth."
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 2
        assert "2023" in text[sentences[0].start : sentences[0].end]

    # -------------------------------------------------------------------------
    # Abbreviation Handling
    # -------------------------------------------------------------------------

    def test_title_abbreviations_not_sentence_end(self):
        """Test that Mr., Dr., etc. don't trigger false sentence breaks."""
        detector = BoundaryDetector()
        text = "Mr. Smith joined the company."
        sentences = detector.find_sentence_boundaries(text)

        # "Mr." should NOT end the sentence
        assert len(sentences) == 1

    def test_corporate_abbreviations_not_sentence_end(self):
        """Test that Inc., Corp., etc. don't trigger false sentence breaks."""
        detector = BoundaryDetector()
        text = "Apple Inc. reported earnings."
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 1

    def test_latin_abbreviations_not_sentence_end(self):
        """Test that e.g., i.e., etc. don't trigger false sentence breaks."""
        detector = BoundaryDetector()
        text = "Metrics, e.g., revenue and margin, improved."
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 1

    def test_country_abbreviation_us(self):
        """Test U.S. abbreviation handling."""
        detector = BoundaryDetector()
        # Note: "U.S." followed by lowercase is NOT a sentence end
        text = "Operations in the U.S. market expanded."
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 1

    # -------------------------------------------------------------------------
    # Question Marks and Exclamation Points
    # -------------------------------------------------------------------------

    def test_question_mark_sentence_end(self):
        """Test that question marks are detected as sentence ends."""
        detector = BoundaryDetector()
        text = "What is CAC? It is Customer Acquisition Cost."
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 2
        assert sentences[0].marker == "?"
        assert sentences[1].marker == "."

    def test_exclamation_mark_sentence_end(self):
        """Test that exclamation marks are detected as sentence ends."""
        detector = BoundaryDetector()
        text = "Revenue exceeded targets! Growth was strong."
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 2
        assert sentences[0].marker == "!"

    # -------------------------------------------------------------------------
    # Table Segment Handling
    # -------------------------------------------------------------------------

    def test_table_segment_single_boundary(self):
        """Test that table segments return single boundary."""
        detector = BoundaryDetector()
        text = "Revenue: $100M. Margin: 25%. Growth: 10%."
        sentences = detector.find_sentence_boundaries(text, segment_type="table")

        # Should be exactly 1 boundary covering entire text
        assert len(sentences) == 1
        assert sentences[0].start == 0
        assert sentences[0].end == len(text)
        assert sentences[0].marker == "[table]"

    def test_table_segment_empty_text(self):
        """Test table segment with empty text."""
        detector = BoundaryDetector()
        sentences = detector.find_sentence_boundaries("", segment_type="table")

        assert sentences == []

    def test_non_table_segment_normal_detection(self):
        """Test that non-table segment types use normal detection."""
        detector = BoundaryDetector()
        text = "First sentence. Second sentence."
        sentences = detector.find_sentence_boundaries(text, segment_type="paragraph")

        # Should detect 2 sentences (not single boundary like tables)
        assert len(sentences) == 2

    # -------------------------------------------------------------------------
    # Edge Cases
    # -------------------------------------------------------------------------

    def test_ellipsis_not_sentence_end(self):
        """Test that ellipsis (...) doesn't trigger sentence break."""
        detector = BoundaryDetector()
        text = "Revenue grew... and margin improved."
        sentences = detector.find_sentence_boundaries(text)

        # Ellipsis should NOT end the sentence
        assert len(sentences) == 1

    def test_multiline_single_sentence(self):
        """Test that newlines don't affect sentence detection."""
        detector = BoundaryDetector()
        text = "Revenue grew 25%\nacross all regions\nin Q1."
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 1
        assert sentences[0].end == len(text)

    def test_multiple_spaces_between_sentences(self):
        """Test sentences separated by multiple spaces."""
        detector = BoundaryDetector()
        text = "First sentence.   Second sentence."
        sentences = detector.find_sentence_boundaries(text)

        assert len(sentences) == 2

    def test_sentence_followed_by_quote(self):
        """Test sentence ending before a quoted section."""
        detector = BoundaryDetector()
        text = 'Revenue grew. "This is great," said the CEO.'
        sentences = detector.find_sentence_boundaries(text)

        # The quote starting with capital should trigger sentence break
        assert len(sentences) == 2

    def test_lowercase_after_period_not_sentence_end(self):
        """Test that period followed by lowercase doesn't end sentence."""
        detector = BoundaryDetector()
        text = "The value was 1.e6 units."
        sentences = detector.find_sentence_boundaries(text)

        # "1.e6" should NOT trigger a sentence break (lowercase after period)
        assert len(sentences) == 1

    def test_single_letter_initial_not_sentence_end(self):
        """Test that single letter initials don't end sentences."""
        detector = BoundaryDetector()
        text = "The company was founded by J. Smith."
        sentences = detector.find_sentence_boundaries(text)

        # "J." should NOT end the sentence
        assert len(sentences) == 1

    # -------------------------------------------------------------------------
    # Integration with in_same_boundary helper
    # -------------------------------------------------------------------------

    def test_in_same_boundary_with_sentences(self):
        """Test in_same_boundary works with sentence boundaries."""
        detector = BoundaryDetector()
        text = "Gross margin was 52.3%. Attrition was 35.1%."
        sentences = detector.find_sentence_boundaries(text)

        # Positions in first sentence
        pos_gross = text.find("Gross")
        pos_52 = text.find("52.3%")
        assert in_same_boundary(pos_gross, pos_52, sentences)

        # Positions in different sentences
        pos_attrition = text.find("Attrition")
        assert not in_same_boundary(pos_gross, pos_attrition, sentences)
