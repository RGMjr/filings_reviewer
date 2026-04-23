"""Unit tests for the Wave B5 bake-off mode of scripts/benchmark_vision.py.

These tests cover:
- `_ProviderEnv` sets + restores the configured env vars.
- Unknown provider names raise ValueError (guarded in both `_ProviderEnv` and
  `_run_benchmark`).
- `_run_bakeoff` aborts mid-sweep when the cumulative spend crosses the cap.

Tests use a monkeypatched `_run_provider` so no real vision API calls fire.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from scripts import benchmark_vision as bv


class TestProviderEnv:
    """The `_ProviderEnv` context manager applies and restores os.environ."""

    def test_sets_configured_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VISION_PROVIDER", raising=False)
        monkeypatch.delenv("VISION_MODEL_OCR", raising=False)
        with bv._ProviderEnv("anthropic"):
            assert os.environ.get("VISION_PROVIDER") == "anthropic"
            assert os.environ.get("VISION_MODEL_OCR") == "claude-sonnet-4-6"
            assert os.environ.get("VISION_MODEL_CHART") == "claude-sonnet-4-6"
            assert os.environ.get("VISION_ROUTING_MODE") == "legacy"

    def test_restores_prior_values_on_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VISION_PROVIDER", "some-prior-value")
        monkeypatch.setenv("VISION_MODEL_OCR", "some-prior-model")
        with bv._ProviderEnv("gemini-pro"):
            assert os.environ["VISION_PROVIDER"] == "gemini"
            assert os.environ["VISION_MODEL_OCR"] == "gemini-2.5-pro"
        assert os.environ["VISION_PROVIDER"] == "some-prior-value"
        assert os.environ["VISION_MODEL_OCR"] == "some-prior-model"

    def test_removes_keys_that_did_not_exist_before(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for k in (
            "VISION_PROVIDER",
            "VISION_MODEL_OCR",
            "VISION_MODEL_CHART",
            "VISION_ROUTING_MODE",
            "VISION_PROVIDER_OCR",
            "VISION_PROVIDER_CHART",
        ):
            monkeypatch.delenv(k, raising=False)
        with bv._ProviderEnv("two-stage"):
            assert os.environ.get("VISION_ROUTING_MODE") == "two_stage"
            assert os.environ.get("VISION_PROVIDER_OCR") == "gemini"
            assert os.environ.get("VISION_PROVIDER_CHART") == "anthropic"
        assert "VISION_ROUTING_MODE" not in os.environ
        assert "VISION_PROVIDER_OCR" not in os.environ
        assert "VISION_PROVIDER_CHART" not in os.environ

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            bv._ProviderEnv("bogus-provider")

    def test_covers_every_bakeoff_provider(self) -> None:
        missing = [p for p in bv.BAKEOFF_PROVIDER_ORDER if p not in bv.PROVIDER_CONFIGS]
        assert missing == [], f"BAKEOFF_PROVIDER_ORDER references unconfigured providers: {missing}"


class TestRunBenchmarkDispatch:
    """`_run_benchmark` dispatches to `_run_provider` and rejects unknowns."""

    def test_rejects_unknown_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        called = {"count": 0}

        def _fake_run_provider(entry: dict[str, Any], provider: str) -> dict[str, Any]:
            called["count"] += 1
            return {}

        monkeypatch.setattr(bv, "_run_provider", _fake_run_provider)
        with pytest.raises(ValueError, match="Unknown provider"):
            bv._run_benchmark([{"img_id": "x", "decision": "chart"}], "nope", None)
        assert called["count"] == 0

    def test_dispatches_for_known_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_run_provider(entry: dict[str, Any], provider: str) -> dict[str, Any]:
            return {
                "img_id": entry["img_id"],
                "predicted_relevant": True,
                "predicted_chart_type": "line",
                "parse_failed": False,
                "cost_usd": 0.01,
                "latency_ms": 100,
                "raw_output": "",
                "title_extracted": "",
                "legend_extracted": "",
                "ocr_cells_extracted": [],
                "axis_labels_extracted": [],
                "tier1_facts_extracted": 0,
                "skipped": False,
                "skip_reason": None,
            }

        monkeypatch.setattr(bv, "_run_provider", _fake_run_provider)
        corpus = [
            {"img_id": "a", "decision": "chart"},
            {"img_id": "b", "decision": "chart"},
        ]
        records = bv._run_benchmark(corpus, "gemini-flash", None)
        assert len(records) == 2
        assert all(r["provider"] == "gemini-flash" for r in records)


class TestBakeoffSpendCap:
    """`_run_bakeoff` stops when cumulative cost crosses the cap."""

    def test_aborts_on_cap(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # Each fake call returns $5 cost; cap is $12 — expect first two
        # providers to run, third to be rejected at the top of the loop.
        per_call_cost = 5.0

        def _fake_run_provider(entry: dict[str, Any], provider: str) -> dict[str, Any]:
            return {
                "img_id": entry["img_id"],
                "predicted_relevant": True,
                "predicted_chart_type": None,
                "parse_failed": False,
                "cost_usd": per_call_cost,
                "latency_ms": 10,
                "raw_output": "",
                "title_extracted": "",
                "legend_extracted": "",
                "ocr_cells_extracted": [],
                "axis_labels_extracted": [],
                "tier1_facts_extracted": 0,
                "skipped": False,
                "skip_reason": None,
            }

        monkeypatch.setattr(bv, "_run_provider", _fake_run_provider)

        corpus = [{"img_id": "only-one", "decision": "chart"}]
        summary = bv._run_bakeoff(
            corpus=corpus,
            limit=None,
            manifest_path=tmp_path / "manifest.json",
            output_root=tmp_path / "out",
            max_usd=12.0,
        )
        # Two providers run before cumulative hits $10, then third provider
        # sees cumulative >= $12 at loop top and aborts BEFORE running.
        # Actually $10 is still below $12, so a third runs -> $15 cumulative,
        # then fourth sees $15 >= $12 and aborts.
        assert summary["aborted_at"] is not None
        assert len(summary["providers_run"]) < len(bv.BAKEOFF_PROVIDER_ORDER)
        assert summary["total_cost_usd"] > 0.0
        summary_path = tmp_path / "out" / "summary.json"
        assert summary_path.exists()
        loaded = json.loads(summary_path.read_text())
        assert loaded["aborted_at"] == summary["aborted_at"]

    def test_runs_all_providers_under_cap(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def _fake_run_provider(entry: dict[str, Any], provider: str) -> dict[str, Any]:
            return {
                "img_id": entry["img_id"],
                "predicted_relevant": True,
                "predicted_chart_type": None,
                "parse_failed": False,
                "cost_usd": 0.001,
                "latency_ms": 10,
                "raw_output": "",
                "title_extracted": "",
                "legend_extracted": "",
                "ocr_cells_extracted": [],
                "axis_labels_extracted": [],
                "tier1_facts_extracted": 0,
                "skipped": False,
                "skip_reason": None,
            }

        monkeypatch.setattr(bv, "_run_provider", _fake_run_provider)
        corpus = [{"img_id": "one", "decision": "chart"}]
        summary = bv._run_bakeoff(
            corpus=corpus,
            limit=None,
            manifest_path=tmp_path / "manifest.json",
            output_root=tmp_path / "out",
            max_usd=100.0,
        )
        assert summary["aborted_at"] is None
        assert summary["providers_run"] == bv.BAKEOFF_PROVIDER_ORDER
        for provider in bv.BAKEOFF_PROVIDER_ORDER:
            assert (tmp_path / "out" / f"{provider}.json").exists()
