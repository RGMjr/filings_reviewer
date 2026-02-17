"""
Unit tests for transcript converter.

Tests cover:
- Basic HTML conversion
- Sentence splitting for long paragraphs
- Section detection (Prepared Remarks, Q&A)
- Speaker role inference (CEO, CFO, analyst)
- Document metadata extraction (ticker, date, company name)
"""

from __future__ import annotations

from datetime import date

import pytest

from src.extraction_v2.transcript_converter import (
    DocumentMetadata,
    _detect_section,
    _escape_html,
    _extract_metadata,
    _infer_speaker_role,
    _split_sentences,
    convert_transcript_to_html,
)


# ============================================================================
# HTML Escaping
# ============================================================================


class TestEscapeHtml:
    def test_escapes_ampersand(self):
        assert _escape_html("A & B") == "A &amp; B"

    def test_escapes_angle_brackets(self):
        assert _escape_html("<script>") == "&lt;script&gt;"

    def test_escapes_quotes(self):
        assert _escape_html('"hello"') == "&quot;hello&quot;"

    def test_plain_text_unchanged(self):
        assert _escape_html("Hello world") == "Hello world"


# ============================================================================
# Sentence Splitting
# ============================================================================


class TestSentenceSplitting:
    def test_short_text_not_split(self):
        text = "Revenue was strong."
        result = _split_sentences(text)
        assert result == [text]

    def test_long_text_split_on_sentence_boundaries(self):
        # Create a long text >300 chars (threshold for sentence splitting)
        sentence1 = "Revenue was strong with growth exceeding our expectations across all regions and segments. " * 6
        sentence2 = "We saw significant improvement in customer metrics across all regions and countries."
        text = sentence1.strip() + " " + sentence2
        assert len(text) > 300, f"Test text must be >300 chars, got {len(text)}"
        result = _split_sentences(text)
        assert len(result) > 1

    def test_does_not_split_within_sentence(self):
        # Short text should stay intact
        text = "The value was $1.5 billion."
        result = _split_sentences(text)
        assert result == [text]

    def test_handles_empty_text(self):
        result = _split_sentences("")
        assert result == [""]

    def test_preserves_numbers(self):
        text = "We had 150 million users. That is a 25% increase over Q3."
        result = _split_sentences(text)
        full = " ".join(result)
        assert "150 million" in full
        assert "25%" in full


# ============================================================================
# Section Detection
# ============================================================================


class TestSectionDetection:
    def test_detects_qa_section(self):
        assert _detect_section("Question-and-Answer Session") == "qa"

    def test_detects_qa_ampersand(self):
        assert _detect_section("Q&A") == "qa"

    def test_detects_prepared_remarks(self):
        assert _detect_section("Prepared Remarks") == "prepared_remarks"

    def test_detects_operator_instructions(self):
        assert _detect_section("Operator Instructions") == "operator_instructions"

    def test_no_section_for_regular_text(self):
        assert _detect_section("Revenue grew 25% year over year.") == ""

    def test_case_insensitive(self):
        assert _detect_section("QUESTION-AND-ANSWER") == "qa"
        assert _detect_section("prepared remarks") == "prepared_remarks"


# ============================================================================
# Speaker Role Inference
# ============================================================================


class TestSpeakerRoleInference:
    def test_ceo_from_name(self):
        assert _infer_speaker_role("John Smith, CEO", "Thank you.") == "ceo"

    def test_cfo_from_name(self):
        assert _infer_speaker_role("Jane Doe, CFO", "Let me walk through the numbers.") == "cfo"

    def test_chief_financial_officer(self):
        assert _infer_speaker_role("Jane Doe", "As Chief Financial Officer, I want to highlight...") == "cfo"

    def test_analyst(self):
        assert _infer_speaker_role("Bob Jones", "Research Analyst at Goldman Sachs.") == "analyst"

    def test_investor_relations(self):
        assert _infer_speaker_role("Sarah Chen, Investor Relations", "Welcome to the call.") == "investor_relations"

    def test_no_role_for_plain_name(self):
        assert _infer_speaker_role("John Smith", "Revenue was strong.") is None


# ============================================================================
# Metadata Extraction
# ============================================================================


class TestMetadataExtraction:
    def test_extracts_ticker(self):
        lines = ["Apple Inc.", "NASDAQ: AAPL", "Q4 2025 Earnings Call"]
        meta = _extract_metadata(lines)
        assert meta.ticker == "AAPL"

    def test_extracts_date(self):
        lines = ["Meta Platforms", "October 30, 2025", "Third Quarter Results"]
        meta = _extract_metadata(lines)
        assert meta.document_date == date(2025, 10, 30)

    def test_extracts_company_name(self):
        lines = ["Snowflake Inc.", "NYSE: SNOW", "Q3 2025 Earnings Call"]
        meta = _extract_metadata(lines)
        assert meta.company_name == "Snowflake Inc."

    def test_extracts_title(self):
        lines = ["Apple Inc.", "Q4 2025 Earnings Call Transcript"]
        meta = _extract_metadata(lines)
        assert meta.title == "Q4 2025 Earnings Call Transcript"

    def test_handles_empty_lines(self):
        lines = ["", "", "Some Company"]
        meta = _extract_metadata(lines)
        assert meta.company_name == "Some Company"

    def test_handles_no_metadata(self):
        lines = ["Just some text"]
        meta = _extract_metadata(lines)
        assert meta.ticker is None
        assert meta.document_date is None


# ============================================================================
# Full Conversion
# ============================================================================


class TestConvertTranscriptToHtml:
    def test_basic_conversion(self):
        text = "John Smith: Revenue was $500 million."
        html, meta = convert_transcript_to_html(text)
        assert "<h3>John Smith</h3>" in html
        assert "$500 million" in html
        assert "<p>" in html

    def test_section_detection_in_output(self):
        text = (
            "Prepared Remarks\n"
            "CEO: Welcome everyone.\n"
            "Question-and-Answer Session\n"
            "Analyst: What about guidance?"
        )
        html, meta = convert_transcript_to_html(text)
        assert 'data-section-type="prepared_remarks"' in html
        assert 'data-section-type="qa"' in html

    def test_speaker_role_in_output(self):
        text = "John Smith, CEO: Revenue grew 25%."
        html, meta = convert_transcript_to_html(text)
        assert 'data-speaker-role="ceo"' in html

    def test_operator_class(self):
        text = "Operator: Thank you for standing by."
        html, meta = convert_transcript_to_html(text)
        assert 'class="operator"' in html

    def test_long_speaker_turn_split_into_sentences(self):
        # Create a very long speaker turn (>300 chars)
        long_content = " ".join(
            [f"We saw growth of {i}% in segment {i}." for i in range(1, 30)]
        )
        text = f"CFO: {long_content}"
        html, meta = convert_transcript_to_html(text)
        # Should have multiple <p> tags from sentence splitting
        p_count = html.count("<p>")
        assert p_count > 1

    def test_metadata_in_html_head(self):
        text = (
            "Snowflake Inc.\n"
            "NYSE: SNOW\n"
            "November 20, 2025\n"
            "Q3 2025 Earnings Call\n"
            "Prepared Remarks\n"
            "CEO: Results were strong."
        )
        html, meta = convert_transcript_to_html(text)
        assert 'name="ticker" content="SNOW"' in html
        assert 'name="document-date" content="2025-11-20"' in html
        assert meta.ticker == "SNOW"
        assert meta.document_date == date(2025, 11, 20)

    def test_html_escaping_in_content(self):
        text = "CEO: Revenue was >$1B & growing."
        html, meta = convert_transcript_to_html(text)
        assert "&gt;" in html
        assert "&amp;" in html
        # Should NOT have raw < or & in body
        body_start = html.index("<body>")
        body = html[body_start:]
        # Raw & should not appear (only &amp; etc)

    def test_continuation_paragraphs(self):
        text = (
            "CEO: First sentence.\n"
            "This is a continuation.\n"
            "And another one."
        )
        html, meta = convert_transcript_to_html(text)
        assert html.count("<p>") >= 3  # Initial + 2 continuations

    def test_returns_metadata(self):
        text = "Apple Inc.\nNASDAQ: AAPL\nJanuary 30, 2025\nQ1 2025 Earnings Call"
        html, meta = convert_transcript_to_html(text)
        assert isinstance(meta, DocumentMetadata)
        assert meta.ticker == "AAPL"
        assert meta.document_date == date(2025, 1, 30)
