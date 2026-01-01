"""Tests for prompt templates module."""


import pytest

from src.llm.prompts import PromptTemplates


class TestPromptGeneration:
    """Tests for prompt generation methods."""

    def test_value_extraction_from_text_includes_metric_names(self):
        """Test value extraction prompt includes metric names."""
        prompt = PromptTemplates.value_extraction_from_text(
            segment_text="Sample text",
            metric_names="active_users, churn_rate",
        )

        assert "active_users, churn_rate" in prompt
        assert "Metrics to look for:" in prompt

    def test_value_extraction_from_text_includes_segment(self):
        """Test value extraction prompt includes segment text."""
        segment = "We had 10 million users as of December 31, 2023."
        prompt = PromptTemplates.value_extraction_from_text(
            segment_text=segment,
            metric_names="active_users",
        )

        assert segment in prompt
        assert "TEXT SEGMENT:" in prompt

    def test_value_extraction_from_text_includes_cohort_guidance(self):
        """Test value extraction prompt includes cohort detection guidance."""
        prompt = PromptTemplates.value_extraction_from_text(
            segment_text="Sample text",
            metric_names="active_users",
        )

        # Prompt includes cohort_label as an output field
        assert "cohort_label" in prompt

    def test_value_extraction_from_text_returns_json_instruction(self):
        """Test value extraction prompt instructs JSON output."""
        prompt = PromptTemplates.value_extraction_from_text(
            segment_text="Sample text",
            metric_names="active_users",
        )

        assert "JSON array" in prompt

    def test_value_extraction_from_table_includes_html(self):
        """Test table extraction prompt includes HTML structure."""
        table_html = "<table><tr><td>Revenue</td></tr></table>"
        prompt = PromptTemplates.value_extraction_from_table(
            table_text="Revenue data",
            table_html=table_html,
            metric_names="revenue",
        )

        assert "TABLE HTML" in prompt
        assert "<table>" in prompt

    def test_value_extraction_from_table_truncates_long_html(self):
        """Test table extraction prompt truncates very long HTML."""
        long_html = "<table>" + "x" * 2000 + "</table>"
        prompt = PromptTemplates.value_extraction_from_table(
            table_text="Data",
            table_html=long_html,
            metric_names="metric",
        )

        # Should truncate HTML to 1000 chars and add "..."
        assert "..." in prompt
        # The HTML portion should be truncated (not the full prompt)
        # The template truncates to table_html[:1000]
        assert long_html not in prompt  # Full HTML should not be in prompt

    def test_value_extraction_from_table_includes_row_column_labels(self):
        """Test table extraction prompt asks for row/column labels."""
        prompt = PromptTemplates.value_extraction_from_table(
            table_text="Data",
            table_html="<table></table>",
            metric_names="metric",
        )

        assert "row_label" in prompt
        assert "column_label" in prompt

    def test_definition_extraction_prompt_format(self):
        """Test definition extraction prompt format."""
        prompt = PromptTemplates.definition_extraction(
            segment_text="We define MAU as users who log in monthly.",
            metric_names="monthly_active_users",
        )

        assert "monthly_active_users" in prompt
        assert "We define MAU as" in prompt
        assert "definition_text" in prompt

    def test_definition_extraction_includes_patterns(self):
        """Test definition extraction prompt includes search patterns."""
        prompt = PromptTemplates.definition_extraction(
            segment_text="Sample text",
            metric_names="metric",
        )

        assert "We define X as" in prompt
        assert "X is calculated by" in prompt
        assert "We measure X as" in prompt

    def test_classification_prompt_content(self):
        """Test classification prompt format."""
        prompt = PromptTemplates.classification_prompt(
            segment_text="Our MAU grew to 10 million users."
        )

        assert "Our MAU grew to 10 million users." in prompt
        assert "contains_numeric_values" in prompt
        assert "contains_definition" in prompt
        assert "contains_methodology" in prompt
        assert "metric_categories" in prompt

    def test_system_value_extraction_contains_priority_metrics(self):
        """Test system message contains priority metrics."""
        system_msg = PromptTemplates.SYSTEM_VALUE_EXTRACTION

        assert "Core Metrics:" in system_msg
        assert "Extended Metrics:" in system_msg
        assert "New customers acquired" in system_msg
        assert "Customer acquisition cost" in system_msg

    def test_system_definition_extraction_content(self):
        """Test system definition extraction message content."""
        system_msg = PromptTemplates.SYSTEM_DEFINITION_EXTRACTION

        assert "definitions" in system_msg.lower()
        assert "SEC filings" in system_msg

    def test_system_value_extraction_excludes_projections(self):
        """Test system prompt instructs to exclude forward-looking data."""
        prompt = PromptTemplates.SYSTEM_VALUE_EXTRACTION
        assert "forward-looking" in prompt.lower() or "projection" in prompt.lower()

    def test_value_extraction_from_text_verbatim_quote(self):
        """Test text extraction emphasizes verbatim quotes."""
        prompt = PromptTemplates.value_extraction_from_text("sample", "metrics")
        assert "verbatim" in prompt.lower() or "EXACT" in prompt

    def test_value_extraction_from_text_excludes_projections(self):
        """Test text extraction excludes projections."""
        prompt = PromptTemplates.value_extraction_from_text("sample", "metrics")
        assert "expect" in prompt.lower() or "projection" in prompt.lower()


class TestParseJsonResponse:
    """Tests for JSON response parsing."""

    def test_parse_json_response_valid_array(self):
        """Test parsing valid JSON array."""
        response = '[{"metric": "users", "value": 100}]'
        result = PromptTemplates.parse_json_response(response)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0]["metric"] == "users"

    def test_parse_json_response_valid_object(self):
        """Test parsing valid JSON object."""
        response = '{"contains_numeric_values": true}'
        result = PromptTemplates.parse_json_response(response)

        assert isinstance(result, dict)
        assert result["contains_numeric_values"] is True

    def test_parse_json_response_strips_markdown_fence_json(self):
        """Test parsing strips ```json markdown fence."""
        response = '```json\n[{"metric": "users"}]\n```'
        result = PromptTemplates.parse_json_response(response)

        assert isinstance(result, list)
        assert result[0]["metric"] == "users"

    def test_parse_json_response_strips_plain_markdown_fence(self):
        """Test parsing strips plain ``` markdown fence."""
        response = '```\n[{"metric": "users"}]\n```'
        result = PromptTemplates.parse_json_response(response)

        assert isinstance(result, list)

    def test_parse_json_response_handles_code_blocks_with_extra_text(self):
        """Test parsing handles code blocks with surrounding text."""
        response = """Here is the extracted data:
```json
[{"metric": "users", "value": 100}]
```
Let me know if you need more details."""

        result = PromptTemplates.parse_json_response(response)
        assert isinstance(result, list)

    def test_parse_json_response_finds_json_in_text(self):
        """Test parsing finds JSON embedded in plain text."""
        response = """Based on my analysis, the extracted metrics are:
[{"metric_name": "active_users", "value": "10"}]
That's all I found."""

        result = PromptTemplates.parse_json_response(response)
        assert isinstance(result, list)
        assert result[0]["metric_name"] == "active_users"

    def test_parse_json_response_empty_array(self):
        """Test parsing empty JSON array."""
        response = "[]"
        result = PromptTemplates.parse_json_response(response)

        assert result == []

    def test_parse_json_response_raises_on_invalid_json(self):
        """Test parsing raises ValueError on invalid JSON."""
        response = "This is not valid JSON at all"

        with pytest.raises(ValueError, match="Failed to parse JSON"):
            PromptTemplates.parse_json_response(response)

    def test_parse_json_response_regex_match_still_invalid(self):
        """Test parsing when regex finds something that looks like JSON but isn't valid."""
        # This triggers the fallback regex search, finds [invalid], but it still fails to parse
        response = "Here is the result: [not, valid, json, {unclosed"

        with pytest.raises(ValueError, match="Failed to parse JSON"):
            PromptTemplates.parse_json_response(response)

    def test_parse_json_response_preserves_whitespace_in_values(self):
        """Test parsing preserves whitespace in JSON values."""
        response = '[{"quote": "We had   10 million   users"}]'
        result = PromptTemplates.parse_json_response(response)

        assert "   10 million   " in result[0]["quote"]


class TestValidateValueExtractionResponse:
    """Tests for value extraction response validation."""

    def test_validate_value_extraction_response_valid(
        self, sample_value_extraction_response
    ):
        """Test validation passes for valid response."""
        result = PromptTemplates.validate_value_extraction_response(
            sample_value_extraction_response
        )

        assert result is True

    def test_validate_value_extraction_response_empty_array_valid(self):
        """Test validation passes for empty array."""
        result = PromptTemplates.validate_value_extraction_response([])

        assert result is True

    def test_validate_value_extraction_response_non_list_invalid(self):
        """Test validation fails for non-list response."""
        result = PromptTemplates.validate_value_extraction_response(
            {"metric_name": "users"}
        )

        assert result is False

    def test_validate_value_extraction_response_non_dict_item_invalid(self):
        """Test validation fails when list contains non-dict."""
        result = PromptTemplates.validate_value_extraction_response(
            [{"metric_name": "users", "value": "100", "period": "2023"}, "invalid"]
        )

        assert result is False

    def test_validate_value_extraction_response_missing_metric_name(self):
        """Test validation fails when metric_name is missing."""
        result = PromptTemplates.validate_value_extraction_response(
            [{"value": "100", "period": "2023"}]
        )

        assert result is False

    def test_validate_value_extraction_response_missing_value(self):
        """Test validation fails when value is missing."""
        result = PromptTemplates.validate_value_extraction_response(
            [{"metric_name": "users", "period": "2023"}]
        )

        assert result is False

    def test_validate_value_extraction_response_missing_period(self):
        """Test validation fails when period is missing."""
        result = PromptTemplates.validate_value_extraction_response(
            [{"metric_name": "users", "value": "100"}]
        )

        assert result is False

    def test_validate_value_extraction_response_optional_fields_ok(self):
        """Test validation passes when optional fields are present."""
        data = [
            {
                "metric_name": "users",
                "value": "100",
                "period": "2023",
                "units": "millions",
                "cohort_label": "2022 Cohort",
                "quote": "We had 100 million users",
            }
        ]

        result = PromptTemplates.validate_value_extraction_response(data)

        assert result is True


class TestValidateDefinitionExtractionResponse:
    """Tests for definition extraction response validation."""

    def test_validate_definition_extraction_response_valid(
        self, sample_definition_extraction_response
    ):
        """Test validation passes for valid response."""
        result = PromptTemplates.validate_definition_extraction_response(
            sample_definition_extraction_response
        )

        assert result is True

    def test_validate_definition_extraction_response_empty_array_valid(self):
        """Test validation passes for empty array."""
        result = PromptTemplates.validate_definition_extraction_response([])

        assert result is True

    def test_validate_definition_extraction_response_non_list_invalid(self):
        """Test validation fails for non-list response."""
        result = PromptTemplates.validate_definition_extraction_response(
            {"metric_name": "users", "definition_text": "...", "quote": "..."}
        )

        assert result is False

    def test_validate_definition_extraction_response_non_dict_item_invalid(self):
        """Test validation fails when list contains non-dict items."""
        result = PromptTemplates.validate_definition_extraction_response(
            [
                {"metric_name": "mau", "definition_text": "users", "quote": "..."},
                "invalid string item",  # This should cause failure
            ]
        )

        assert result is False

    def test_validate_definition_extraction_response_missing_metric_name(self):
        """Test validation fails when metric_name is missing."""
        result = PromptTemplates.validate_definition_extraction_response(
            [{"definition_text": "users who log in", "quote": "We define..."}]
        )

        assert result is False

    def test_validate_definition_extraction_response_missing_definition_text(self):
        """Test validation fails when definition_text is missing."""
        result = PromptTemplates.validate_definition_extraction_response(
            [{"metric_name": "mau", "quote": "We define..."}]
        )

        assert result is False

    def test_validate_definition_extraction_response_missing_quote(self):
        """Test validation fails when quote is missing."""
        result = PromptTemplates.validate_definition_extraction_response(
            [{"metric_name": "mau", "definition_text": "users who log in"}]
        )

        assert result is False

    def test_validate_definition_extraction_response_with_calculation_flag(self):
        """Test validation passes with includes_calculation flag."""
        data = [
            {
                "metric_name": "nrr",
                "definition_text": "revenue from existing customers divided by...",
                "includes_calculation": True,
                "quote": "NRR is calculated as...",
            }
        ]

        result = PromptTemplates.validate_definition_extraction_response(data)

        assert result is True
