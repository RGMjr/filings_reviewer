"""
Unit tests for keyword_config alias functions.

Tests the metric ID alias system that enables matching between canonical
metric IDs and alternative identifiers used in gold standard files.
"""

import pytest

from src.extraction.keyword_config import (
    get_aliases,
    get_all_equivalent_ids,
    get_metric_keywords,
    KeywordConfigError,
    list_metrics,
    metrics_are_equivalent,
    reload_config,
    resolve_to_canonical,
)


class TestGetAliases:
    """Tests for get_aliases function."""

    def test_returns_dict(self):
        """get_aliases returns a dictionary."""
        aliases = get_aliases()
        assert isinstance(aliases, dict)

    def test_aliases_are_lists_of_strings(self):
        """Each alias entry should be a list of strings."""
        aliases = get_aliases()
        for metric_id, alias_list in aliases.items():
            assert isinstance(alias_list, list), f"{metric_id} aliases should be a list"
            assert all(isinstance(a, str) for a in alias_list), f"{metric_id} aliases should be strings"
            assert all(a.startswith("cm_") for a in alias_list), f"{metric_id} aliases should start with cm_"

    def test_excludes_yaml_anchors(self):
        """YAML anchor keys (starting with _) should be excluded."""
        aliases = get_aliases()
        for metric_id in aliases.keys():
            assert not metric_id.startswith("_"), f"Should not include YAML anchor {metric_id}"

    def test_includes_known_alias(self):
        """Should include the known cm_customers_period_end -> cm_active_customers_total alias."""
        aliases = get_aliases()
        assert "cm_customers_period_end" in aliases
        assert "cm_active_customers_total" in aliases["cm_customers_period_end"]


class TestResolveToCanonical:
    """Tests for resolve_to_canonical function."""

    def test_canonical_returns_unchanged(self):
        """Canonical ID returns unchanged."""
        result = resolve_to_canonical("cm_arr")
        assert result == "cm_arr"

    def test_unknown_id_returns_unchanged(self):
        """Unknown ID returns unchanged."""
        result = resolve_to_canonical("unknown_metric_xyz")
        assert result == "unknown_metric_xyz"

    def test_empty_string_returns_empty(self):
        """Empty string input returns empty string."""
        result = resolve_to_canonical("")
        assert result == ""

    def test_alias_resolves_to_canonical(self):
        """cm_active_customers_total resolves to cm_customers_period_end."""
        result = resolve_to_canonical("cm_active_customers_total")
        assert result == "cm_customers_period_end"

    def test_canonical_id_stays_canonical(self):
        """cm_customers_period_end stays as cm_customers_period_end."""
        result = resolve_to_canonical("cm_customers_period_end")
        assert result == "cm_customers_period_end"


class TestGetAllEquivalentIds:
    """Tests for get_all_equivalent_ids function."""

    def test_no_aliases_returns_input_only(self):
        """Metric without aliases returns set with just input."""
        result = get_all_equivalent_ids("cm_arr")
        assert "cm_arr" in result
        assert len(result) == 1

    def test_includes_canonical_and_aliases(self):
        """Returns set with canonical and all aliases for cm_customers_period_end."""
        result = get_all_equivalent_ids("cm_customers_period_end")
        assert "cm_customers_period_end" in result
        assert "cm_active_customers_total" in result

    def test_alias_input_returns_full_set(self):
        """Alias as input also returns full set."""
        result = get_all_equivalent_ids("cm_active_customers_total")
        assert "cm_customers_period_end" in result
        assert "cm_active_customers_total" in result

    def test_unknown_id_returns_set_with_input(self):
        """Unknown ID returns set containing just that ID."""
        result = get_all_equivalent_ids("unknown_metric_xyz")
        assert result == {"unknown_metric_xyz"}


class TestMetricsAreEquivalent:
    """Tests for metrics_are_equivalent function."""

    def test_same_id_is_equivalent(self):
        """Same ID is equivalent to itself."""
        assert metrics_are_equivalent("cm_arr", "cm_arr") is True

    def test_different_ids_not_equivalent(self):
        """Different non-aliased IDs are not equivalent."""
        assert metrics_are_equivalent("cm_arr", "cm_mrr") is False

    def test_canonical_and_alias_are_equivalent(self):
        """cm_customers_period_end and cm_active_customers_total are equivalent."""
        assert metrics_are_equivalent("cm_customers_period_end", "cm_active_customers_total") is True
        assert metrics_are_equivalent("cm_active_customers_total", "cm_customers_period_end") is True

    def test_empty_string_handling(self):
        """Empty strings are handled gracefully."""
        assert metrics_are_equivalent("", "") is True
        assert metrics_are_equivalent("cm_arr", "") is False


class TestAliasIntegration:
    """Integration tests for alias system."""

    def test_aliases_reference_existing_canonical(self):
        """All canonical metric IDs with aliases should exist in config."""
        aliases = get_aliases()
        all_metrics = set(list_metrics())

        for canonical in aliases.keys():
            assert canonical in all_metrics, f"Canonical {canonical} should be in metrics list"

    def test_no_circular_aliases(self):
        """Aliases should not create circular references."""
        aliases = get_aliases()
        all_aliases = set()

        for alias_list in aliases.values():
            all_aliases.update(alias_list)

        # No alias should also be a canonical (which would have its own aliases)
        for alias in all_aliases:
            assert alias not in aliases, f"Alias {alias} cannot also be a canonical with aliases"

    def test_keyword_config_loads_with_aliases(self):
        """Config should load successfully with aliases field."""
        # This tests that the validation passes
        reload_config()
        keywords = get_metric_keywords()
        assert "cm_customers_period_end" in keywords


class TestAliasValidation:
    """Tests for alias validation in config loading."""

    def test_valid_aliases_accepted(self):
        """Valid aliases should not raise errors."""
        # If we got here, the config loaded successfully
        aliases = get_aliases()
        assert isinstance(aliases, dict)

    # Note: We can't easily test invalid alias configurations without
    # creating a separate test config file, so we rely on the validation
    # code being covered by the config loading that happens in other tests.
