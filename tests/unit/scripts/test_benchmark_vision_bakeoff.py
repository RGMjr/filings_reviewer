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

        def _fake_run_provider(
            entry: dict[str, Any], provider: str, mode: str = "detect"
        ) -> dict[str, Any]:
            called["count"] += 1
            return {}

        monkeypatch.setattr(bv, "_run_provider", _fake_run_provider)
        with pytest.raises(ValueError, match="Unknown provider"):
            bv._run_benchmark([{"img_id": "x", "decision": "chart"}], "nope", None)
        assert called["count"] == 0

    def test_dispatches_for_known_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _fake_run_provider(
            entry: dict[str, Any], provider: str, mode: str = "detect"
        ) -> dict[str, Any]:
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

        def _fake_run_provider(
            entry: dict[str, Any], provider: str, mode: str = "detect"
        ) -> dict[str, Any]:
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
        def _fake_run_provider(
            entry: dict[str, Any], provider: str, mode: str = "detect"
        ) -> dict[str, Any]:
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


class TestChartReadMode:
    """Wave B5.x `--mode chart-read` dispatch + scoring."""

    def test_chart_read_order_includes_two_stage(self) -> None:
        assert "two-stage" in bv.BAKEOFF_PROVIDER_ORDER_CHART_READ
        assert "two-stage" not in bv.BAKEOFF_PROVIDER_ORDER
        # Detect order is a strict subset (same providers minus two-stage).
        assert set(bv.BAKEOFF_PROVIDER_ORDER).issubset(set(bv.BAKEOFF_PROVIDER_ORDER_CHART_READ))

    def test_bakeoff_order_for_resolves_per_mode(self) -> None:
        assert bv._bakeoff_order_for("detect") == list(bv.BAKEOFF_PROVIDER_ORDER)
        assert bv._bakeoff_order_for("chart-read") == list(bv.BAKEOFF_PROVIDER_ORDER_CHART_READ)

    def test_run_benchmark_rejects_unknown_mode(self) -> None:
        with pytest.raises(ValueError, match="Unknown mode"):
            bv._run_benchmark([{"img_id": "x", "decision": "chart"}], "current", None, mode="bogus")

    def test_run_provider_dispatches_on_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """`_run_provider` routes to detect vs chart-read branch on `mode`."""
        calls: list[str] = []

        def _fake_detect(entry: Any, provider: Any, image_bytes: Any, skel: Any, t0: Any) -> Any:
            calls.append("detect")
            return {**skel, "predicted_relevant": True, "cost_usd": 0.001}

        def _fake_chart(entry: Any, provider: Any, image_bytes: Any, skel: Any, t0: Any) -> Any:
            calls.append("chart-read")
            return {
                **skel,
                "predicted_relevant": True,
                "cost_usd": 0.01,
                "title_extracted": "t",
                "axis_labels_extracted": ["x", "y"],
                "legend_extracted": "series",
                "extracted_points": [{"value": 44.4, "period": "2017", "source": "annotation"}],
            }

        class _FakeStorage:
            def get_bytes(self, key: str) -> bytes:
                return b"\xff\xd8\xffJPEG"

        monkeypatch.setattr(bv, "_run_provider_detect", _fake_detect)
        monkeypatch.setattr(bv, "_run_provider_chart_read", _fake_chart)
        monkeypatch.setattr("src.infra.image_storage.get_image_storage", lambda: _FakeStorage())

        entry = {"img_id": "x", "storage_key": "Farfetch_Limited/g.jpg", "decision": "chart"}
        bv._run_provider(entry, "gemini-flash", mode="detect")
        bv._run_provider(entry, "gemini-flash", mode="chart-read")
        assert calls == ["detect", "chart-read"]

    def test_run_provider_rejects_unknown_mode(self) -> None:
        with pytest.raises(ValueError, match="Unknown mode"):
            bv._run_provider({"img_id": "x", "storage_key": "x/y.jpg"}, "current", mode="bogus")

    def test_flatten_chart_points_handles_series_and_annotations(self) -> None:
        series = [
            {"name": "A", "points": [{"x": "2020", "y": 10.5}, {"x": "2021", "y": "bad"}]},
            {"name": "B", "points": [{"x": "2020", "y": 20}]},
        ]
        annotations = [
            {"text": "44.4%", "value": 44.4, "period": "2017"},
            {"text": "n/a", "value": None},
            {"text": "bad-value", "value": "unparseable"},
        ]
        out = bv._flatten_chart_points(series, annotations)
        values = sorted(p["value"] for p in out)
        assert values == [10.5, 20.0, 44.4]
        assert any(p["source"] == "annotation" for p in out)
        assert any(p["source"] == "series" for p in out)

    def test_load_chart_ground_truth_empty_without_mapping(self) -> None:
        """No ground_truth_value_ids → no reference points."""
        entry = {
            "img_id": "no-gt",
            "storage_key": "Farfetch_Limited/g607688g12o45.jpg",
        }
        assert bv._load_chart_ground_truth(entry) == []

    def test_load_chart_ground_truth_pulls_mapped_rows(self) -> None:
        """Farfetch g09d00 entry maps to the 2 CSV chart rows (10001, 10100)."""
        entry = {
            "img_id": "gs-farfetch-g607688g09d00",
            "storage_key": "Farfetch_Limited/g607688g09d00.jpg",
            "ground_truth_value_ids": [10001, 10100],
        }
        rows = bv._load_chart_ground_truth(entry)
        assert len(rows) == 2
        values = sorted(r["value"] for r in rows)
        assert values == [44.4, 55.6]
        assert all(r["metric_id"] == "cm_revenue_by_cohort" for r in rows)

    def test_chart_read_end_to_end_per_point_scoring(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Chart-read run against a mapped fixture entry scores TP/FP/FN.

        Uses a fake `_run_provider` that mimics a model returning 44.4 +
        a spurious 99.9. Ground-truth is [44.4, 55.6] → TP=1, FP=1, FN=1.
        """

        def _fake_run_provider(
            entry: dict[str, Any], provider: str, mode: str = "detect"
        ) -> dict[str, Any]:
            assert mode == "chart-read"
            return {
                "img_id": entry["img_id"],
                "predicted_relevant": True,
                "predicted_chart_type": "bar",
                "parse_failed": False,
                "cost_usd": 0.01,
                "latency_ms": 100,
                "raw_output": "",
                "title_extracted": "Revenue by cohort",
                "legend_extracted": "",
                "ocr_cells_extracted": [],
                "axis_labels_extracted": ["Year", "%"],
                "tier1_facts_extracted": 0,
                "extracted_points": [
                    {"value": 44.4, "period": "2017", "source": "annotation"},
                    {"value": 99.9, "period": "2017", "source": "annotation"},
                ],
                "skipped": False,
                "skip_reason": None,
            }

        monkeypatch.setattr(bv, "_run_provider", _fake_run_provider)

        corpus = [
            {
                "img_id": "gs-farfetch-g607688g09d00",
                "storage_key": "Farfetch_Limited/g607688g09d00.jpg",
                "decision": "relevant",
                "ground_truth_value_ids": [10001, 10100],
            }
        ]
        records = bv._run_benchmark(corpus, "gemini-flash", None, mode="chart-read")
        assert len(records) == 1
        r = records[0]
        assert r["data_value_tp"] == 1
        assert r["data_value_fp"] == 1
        assert r["data_value_fn"] == 1
        assert len(r["reference_points"]) == 2

        metrics = bv._build_eval_results(records)
        # P=1/(1+1)=0.5, R=1/(1+1)=0.5, F1=0.5, n_scored=1
        assert metrics["data_value_precision"] == 0.5
        assert metrics["data_value_recall"] == 0.5
        assert metrics["data_value_f1"] == 0.5
        assert metrics["n_images_scored_on_data"] == 1
