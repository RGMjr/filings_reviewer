"""
Unit tests for chart_prompts.py — Pass 1 classification and Pass 2 type-specific prompts.

Tests cover:
- Pass 1 classification prompt returns non-empty string
- Pass 2 prompts embed axis context from Pass 1
- interpolation_enabled=True adds interpolation instructions
- get_pass2_prompt dispatch for all chart types
"""

from __future__ import annotations

import pytest

from src.extraction_v2.chart_prompts import (
    get_area_chart_prompt,
    get_bar_chart_prompt,
    get_classification_prompt,
    get_generic_chart_prompt,
    get_line_chart_prompt,
    get_pass2_prompt,
    get_pie_chart_prompt,
    get_stacked_bar_prompt,
)

# ============================================================================
# Pass 1 Classification Prompt
# ============================================================================


def test_classification_prompt_returns_non_empty_string() -> None:
    """get_classification_prompt() returns a non-empty string."""
    prompt = get_classification_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 100


def test_classification_prompt_instructs_no_value_extraction() -> None:
    """Pass 1 prompt explicitly says NOT to extract data values."""
    prompt = get_classification_prompt()
    assert "NOT" in prompt or "no value" in prompt.lower() or "do not extract" in prompt.lower()


def test_classification_prompt_requests_json_keys() -> None:
    """Pass 1 prompt requests all required JSON keys."""
    prompt = get_classification_prompt()
    required_keys = [
        "chart_type",
        "has_data_labels",
        "x_label",
        "y_label",
        "y_min",
        "y_max",
        "y_ticks",
        "x_categories",
        "legend_entries",
        "estimated_series_count",
        "confidence",
    ]
    for key in required_keys:
        assert key in prompt, f"Key '{key}' missing from classification prompt"


# ============================================================================
# Pass 2 Prompts — axis context embedding
# ============================================================================

SAMPLE_PASS1_CONTEXT = {
    "chart_type": "bar",
    "has_data_labels": True,
    "x_label": "Year",
    "y_label": "Revenue ($M)",
    "y_min": 0,
    "y_max": 500,
    "y_ticks": [0, 100, 200, 300, 400, 500],
    "x_categories": ["2020", "2021", "2022"],
    "legend_entries": ["Enterprise", "SMB"],
}


def test_bar_chart_prompt_embeds_axis_context() -> None:
    """get_bar_chart_prompt() embeds the Pass 1 axis context in the prompt."""
    prompt = get_bar_chart_prompt(SAMPLE_PASS1_CONTEXT)
    assert "Revenue ($M)" in prompt
    assert "Year" in prompt
    assert "500" in prompt  # y_max
    assert "Enterprise" in prompt or "SMB" in prompt  # legend entries


def test_line_chart_prompt_embeds_axis_context() -> None:
    """get_line_chart_prompt() embeds the Pass 1 axis context in the prompt."""
    prompt = get_line_chart_prompt(SAMPLE_PASS1_CONTEXT)
    assert "Revenue ($M)" in prompt
    assert "Year" in prompt


def test_pie_chart_prompt_returns_non_empty_string() -> None:
    """get_pie_chart_prompt() returns a non-empty string with pie-specific instructions."""
    prompt = get_pie_chart_prompt(SAMPLE_PASS1_CONTEXT)
    assert isinstance(prompt, str)
    assert len(prompt) > 100
    assert "pie" in prompt.lower() or "slice" in prompt.lower()


def test_stacked_bar_prompt_embeds_axis_context() -> None:
    """get_stacked_bar_prompt() embeds the Pass 1 axis context."""
    prompt = get_stacked_bar_prompt(SAMPLE_PASS1_CONTEXT)
    assert "Revenue ($M)" in prompt


def test_area_chart_prompt_returns_non_empty_string() -> None:
    """get_area_chart_prompt() returns a non-empty prompt."""
    prompt = get_area_chart_prompt(SAMPLE_PASS1_CONTEXT)
    assert isinstance(prompt, str)
    assert len(prompt) > 100


def test_generic_chart_prompt_returns_non_empty_string() -> None:
    """get_generic_chart_prompt() returns a non-empty fallback prompt."""
    prompt = get_generic_chart_prompt({})
    assert isinstance(prompt, str)
    assert len(prompt) > 100


# ============================================================================
# interpolation_enabled=True adds interpolation instructions
# ============================================================================


def test_bar_prompt_without_interpolation_omits_instructions() -> None:
    """When interpolation_enabled=False, interpolation instructions are absent."""
    prompt = get_bar_chart_prompt(SAMPLE_PASS1_CONTEXT, interpolation_enabled=False)
    assert "interpolated" not in prompt.lower() or "interpolated: false" in prompt.lower()


def test_bar_prompt_with_interpolation_adds_instructions() -> None:
    """When interpolation_enabled=True, interpolation instructions are present."""
    prompt = get_bar_chart_prompt(SAMPLE_PASS1_CONTEXT, interpolation_enabled=True)
    assert "interpolation enabled" in prompt.lower() or "interpolated" in prompt.lower()
    # Check for the instruction pattern (quotes may vary)
    assert '"interpolated": true' in prompt or "interpolated: true" in prompt.lower()


def test_line_prompt_with_interpolation_adds_instructions() -> None:
    """interpolation_enabled=True adds instructions to line chart prompt."""
    prompt = get_line_chart_prompt(SAMPLE_PASS1_CONTEXT, interpolation_enabled=True)
    assert "interpolated" in prompt.lower()


def test_generic_prompt_with_interpolation_adds_instructions() -> None:
    """interpolation_enabled=True adds instructions to generic fallback prompt."""
    prompt = get_generic_chart_prompt({}, interpolation_enabled=True)
    assert "interpolated" in prompt.lower()


# ============================================================================
# get_pass2_prompt dispatch
# ============================================================================


@pytest.mark.parametrize(
    "chart_type,expected_keyword",
    [
        ("bar", "bar"),
        ("line", "line"),
        ("pie", "pie"),
        ("stacked_bar", "stacked"),
        ("area", "area"),
        ("unknown", "chart"),  # falls back to generic
        ("invalid_type", "chart"),  # falls back to generic
    ],
)
def test_get_pass2_prompt_dispatches_by_chart_type(
    chart_type: str, expected_keyword: str
) -> None:
    """get_pass2_prompt() dispatches to the correct type-specific prompt."""
    prompt = get_pass2_prompt(chart_type, SAMPLE_PASS1_CONTEXT)
    assert isinstance(prompt, str)
    assert len(prompt) > 100
    assert expected_keyword in prompt.lower()


def test_get_pass2_prompt_passes_interpolation_flag() -> None:
    """get_pass2_prompt() forwards interpolation_enabled to the type-specific function."""
    prompt_no_interp = get_pass2_prompt("bar", SAMPLE_PASS1_CONTEXT, interpolation_enabled=False)
    prompt_with_interp = get_pass2_prompt("bar", SAMPLE_PASS1_CONTEXT, interpolation_enabled=True)
    # The interpolation version should be longer (has extra instructions)
    assert len(prompt_with_interp) > len(prompt_no_interp)
