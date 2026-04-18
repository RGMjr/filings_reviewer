"""Tests for src.shared.keyword_config.match_nearby_text."""

from __future__ import annotations

import textwrap

import pytest

from src.shared.keyword_config import match_nearby_text, reload_config


@pytest.fixture
def custom_yaml(tmp_path):
    """Minimal YAML config for deterministic matcher tests."""
    path = tmp_path / "keywords.yaml"
    path.write_text(
        textwrap.dedent(
            """\
            cm_customer_retention_rate:
              tier: 1
              patterns:
                - '\\bretention\\b'
                - '\\bcustomer\\s+retention\\s+rate\\b'

            cm_new_customers_acquired:
              tier: 1
              patterns:
                - '\\bnew\\s+customers?\\b'
              exclusions:
                - '\\bprospective\\s+new\\s+customers?\\b'
            """
        ).strip()
    )
    reload_config()
    yield str(path)
    reload_config()


def test_empty_text_returns_empty_list(custom_yaml):
    assert match_nearby_text("", config_path=custom_yaml) == []
    assert match_nearby_text(None, config_path=custom_yaml) == []  # type: ignore[arg-type]


def test_no_matches_returns_empty_list(custom_yaml):
    assert match_nearby_text("the quick brown fox", config_path=custom_yaml) == []


def test_single_match(custom_yaml):
    result = match_nearby_text(
        "Our net revenue retention grew this year.", config_path=custom_yaml
    )
    assert result == ["retention"]


def test_multi_metric_match_is_deduped_and_sorted(custom_yaml):
    text = "Customer retention rate was 95% as new customers joined."
    result = match_nearby_text(text, config_path=custom_yaml)
    assert result == sorted(result)
    assert "customer retention rate" in result
    assert "new customers" in result


def test_word_boundaries_honored(custom_yaml):
    # 'retention' has \b on both sides; 'detention' must NOT match.
    assert match_nearby_text("student detention center", config_path=custom_yaml) == []


def test_exclusions_not_applied_to_matcher(custom_yaml):
    # match_nearby_text records pattern hits verbatim; exclusions are for
    # FP filtering of extracted values, not keyword-detection semantics.
    result = match_nearby_text(
        "We target prospective new customers next quarter.",
        config_path=custom_yaml,
    )
    assert "new customers" in result


def test_case_insensitive(custom_yaml):
    # Patterns compiled re.IGNORECASE; output lower-cased for stability.
    result = match_nearby_text("Net Revenue RETENTION grew.", config_path=custom_yaml)
    assert result == ["retention"]


def test_dedupe_across_multiple_hits(custom_yaml):
    text = "retention, retention, and more retention"
    assert match_nearby_text(text, config_path=custom_yaml) == ["retention"]
