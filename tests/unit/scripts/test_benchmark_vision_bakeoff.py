"""Unit tests for the Wave B5 bake-off mode of scripts/benchmark_vision.py.

These tests cover:
- `_ProviderEnv` sets + restores the configured env vars.
- Unknown provider names raise ValueError (guarded in both `_ProviderEnv` and
  `_run_benchmark`).
- `_run_bakeoff` aborts mid-sweep when the cumulative spend crosses the cap.
- `TestCorpusQuery` — gh-196: UNION corpus query aggregation and dedup logic.

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


class TestMetricClassifyMode:
    """metric-classify mode — dispatch, order, scoring, end-to-end."""

    def test_metric_classify_order_excludes_two_stage(self) -> None:
        assert "two-stage" not in bv.BAKEOFF_PROVIDER_ORDER_METRIC_CLASSIFY
        # Every configured classify provider must exist in PROVIDER_CONFIGS.
        missing = [
            p for p in bv.BAKEOFF_PROVIDER_ORDER_METRIC_CLASSIFY if p not in bv.PROVIDER_CONFIGS
        ]
        assert missing == []

    def test_bakeoff_order_for_resolves_metric_classify(self) -> None:
        assert bv._bakeoff_order_for("metric-classify") == list(
            bv.BAKEOFF_PROVIDER_ORDER_METRIC_CLASSIFY
        )

    def test_metric_classify_is_registered_mode(self) -> None:
        assert "metric-classify" in bv.BENCHMARK_MODES

    def test_classify_prompt_enumerates_tiers_from_yaml(self) -> None:
        # All tier-1 ids pulled from yaml must appear in the prompt.
        for metric_id in bv._TIER1_METRIC_IDS:
            assert metric_id in bv.CLASSIFY_PROMPT
        for metric_id in bv._TIER2_METRIC_IDS:
            assert metric_id in bv.CLASSIFY_PROMPT
        # Prompt is JSON-forced — must mention JSON (OpenAI json_object
        # response_format requires the word "JSON" in the prompt).
        assert "JSON" in bv.CLASSIFY_PROMPT

    def test_parse_classify_response_happy_path(self) -> None:
        parsed = bv._parse_classify_response(
            '{"predicted_metrics":["cm_revenue_by_cohort"],'
            '"confidence":0.85,"rejection_reason":null,'
            '"reasoning":"cohort parfait shape"}'
        )
        assert parsed == {
            "predicted_metrics": ["cm_revenue_by_cohort"],
            "confidence": 0.85,
            "rejection_reason": None,
            "reasoning": "cohort parfait shape",
        }

    def test_parse_classify_response_drops_unknown_metric_ids(self) -> None:
        parsed = bv._parse_classify_response(
            '{"predicted_metrics":["cm_revenue_by_cohort","cm_bogus"],'
            '"confidence":0.9,"rejection_reason":null,"reasoning":"x"}'
        )
        assert parsed is not None
        assert parsed["predicted_metrics"] == ["cm_revenue_by_cohort"]

    def test_parse_classify_response_invalid_json(self) -> None:
        assert bv._parse_classify_response("not json at all") is None
        assert bv._parse_classify_response("[]") is None  # not a dict

    def test_parse_classify_response_strips_markdown_fences(self) -> None:
        """Gemini wraps JSON in ```json … ``` fences; parser must unwrap."""
        raw = (
            '```json\n{"predicted_metrics":["cm_arr"],"confidence":0.9,'
            '"rejection_reason":null,"reasoning":"x"}\n```'
        )
        parsed = bv._parse_classify_response(raw)
        assert parsed is not None
        assert parsed["predicted_metrics"] == ["cm_arr"]
        assert parsed["confidence"] == 0.9

    def test_parse_classify_response_coerces_bad_confidence(self) -> None:
        # None confidence → 0.0; out-of-range clamped.
        parsed = bv._parse_classify_response(
            '{"predicted_metrics":[],"confidence":null,"rejection_reason":"decorative","reasoning":""}'
        )
        assert parsed is not None
        assert parsed["confidence"] == 0.0
        parsed = bv._parse_classify_response(
            '{"predicted_metrics":["cm_arr"],"confidence":2.5,"rejection_reason":null,"reasoning":""}'
        )
        assert parsed is not None
        assert parsed["confidence"] == 1.0

    def test_parse_classify_response_coerces_unknown_rejection_reason(self) -> None:
        parsed = bv._parse_classify_response(
            '{"predicted_metrics":[],"confidence":0.1,"rejection_reason":"wibble","reasoning":""}'
        )
        assert parsed is not None
        assert parsed["rejection_reason"] == "other"

    def test_parse_classify_response_drops_reason_when_metrics_present(self) -> None:
        """If the model emits both, the reason is stripped (schema requires null)."""
        parsed = bv._parse_classify_response(
            '{"predicted_metrics":["cm_arr"],"confidence":0.9,'
            '"rejection_reason":"decorative","reasoning":"odd"}'
        )
        assert parsed is not None
        assert parsed["rejection_reason"] is None

    def test_load_manifest_metric_tags_empty_when_missing(self) -> None:
        assert bv._load_manifest_metric_tags({}) == []
        assert bv._load_manifest_metric_tags({"ground_truth_metric_ids": None}) == []

    def test_load_manifest_metric_tags_filters_unknown(self) -> None:
        entry = {"ground_truth_metric_ids": ["cm_revenue_by_cohort", "cm_bogus", " "]}
        assert bv._load_manifest_metric_tags(entry) == ["cm_revenue_by_cohort"]

    def test_run_provider_dispatches_to_classify_branch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []

        def _fake_classify(entry: Any, provider: Any, image_bytes: Any, skel: Any, t0: Any) -> Any:
            calls.append("metric-classify")
            return {
                **skel,
                "predicted_relevant": True,
                "predicted_metrics": ["cm_revenue_by_cohort"],
                "classification_confidence": 0.8,
                "cost_usd": 0.002,
            }

        class _FakeStorage:
            def get_bytes(self, key: str) -> bytes:
                return b"\xff\xd8\xffJPEG"

        monkeypatch.setattr(bv, "_run_provider_metric_classify", _fake_classify)
        monkeypatch.setattr("src.infra.image_storage.get_image_storage", lambda: _FakeStorage())

        entry = {
            "img_id": "x",
            "storage_key": "Farfetch_Limited/g.jpg",
            "decision": "chart",
        }
        bv._run_provider(entry, "gemini-flash", mode="metric-classify")
        assert calls == ["metric-classify"]

    def test_end_to_end_covers_six_reviewer_buckets(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exercise accept/reject/correct/add/partial/skip in one run."""
        # One record per bucket. ``predicted`` is what the fake provider
        # emits; ``reference`` comes from manifest entry ground_truth_metric_ids.
        scenarios = [
            ("accept-img", ["cm_arr"], ["cm_arr"], 0.9),
            ("reject-img", ["cm_arr"], [], 0.9),
            ("correct-img", ["cm_arr"], ["cm_mrr"], 0.8),
            ("add-img", [], ["cm_arr"], 0.2),
            ("partial-img", ["cm_arr", "cm_mrr"], ["cm_arr"], 0.7),
            ("skip-img", [], [], 0.1),
        ]
        prediction_by_id = {img: preds for img, preds, _, _ in scenarios}
        confidence_by_id = {img: conf for img, _, _, conf in scenarios}

        def _fake_run_provider(
            entry: dict[str, Any], provider: str, mode: str = "detect"
        ) -> dict[str, Any]:
            assert mode == "metric-classify"
            img = entry["img_id"]
            preds = prediction_by_id[img]
            conf = confidence_by_id[img]
            return {
                "img_id": img,
                "predicted_relevant": bool(preds),
                "predicted_chart_type": None,
                "parse_failed": False,
                "cost_usd": 0.002,
                "latency_ms": 50,
                "raw_output": "",
                "title_extracted": "",
                "legend_extracted": "",
                "ocr_cells_extracted": [],
                "axis_labels_extracted": [],
                "tier1_facts_extracted": 0,
                "predicted_metrics": preds,
                "classification_confidence": conf,
                "rejection_reason": None,
                "classification_reasoning": "",
                "skipped": False,
                "skip_reason": None,
            }

        monkeypatch.setattr(bv, "_run_provider", _fake_run_provider)

        corpus = [
            {
                "img_id": img,
                "storage_key": f"x/{img}.jpg",
                "decision": "relevant",
                "ground_truth_metric_ids": ref,
            }
            for img, _preds, ref, _conf in scenarios
        ]
        records = bv._run_benchmark(corpus, "gemini-flash", None, mode="metric-classify")
        assert len(records) == 6
        actions = {r["img_id"]: r["reviewer_action"] for r in records}
        assert actions == {
            "accept-img": "accept",
            "reject-img": "reject",
            "correct-img": "correct",
            "add-img": "add",
            "partial-img": "partial",
            "skip-img": "skip",
        }

        metrics = bv._build_eval_results(records)
        # 6 records, one per bucket → every rate is 1/6 and they sum to 1.0.
        assert metrics["accept_rate"] == pytest.approx(1 / 6)
        assert metrics["reject_rate"] == pytest.approx(1 / 6)
        assert metrics["correct_rate"] == pytest.approx(1 / 6)
        assert metrics["add_rate"] == pytest.approx(1 / 6)
        assert metrics["partial_rate"] == pytest.approx(1 / 6)
        assert metrics["skip_rate"] == pytest.approx(1 / 6)
        assert metrics["auto_disposition_rate"] == pytest.approx(2 / 6)
        # Scored-on-tags subset excludes skip-img AND reject-img (reference
        # empty in both): 4 records contribute to tag P/R/F1.
        assert metrics["n_images_scored_on_metric_tags"] == 4


class TestCorpusQuery:
    """gh-196: UNION corpus aggregation dedup logic in --build-corpus mode.

    These tests exercise the Python-level dedup applied after the two separate
    DB queries (_CORPUS_QUERY_LEGACY + _CORPUS_QUERY_CONFIRMATIONS).  They do
    not require a real DB — they test the in-memory logic directly.

    Rules under test (must match export_image_training_data.export_sec_rows):
      - Legacy-only row: appears in output unchanged.
      - Confirmation-only row: appears in output with chart_type=None.
      - Overlap (same img_id in both): legacy row wins; confirmation row dropped.
    """

    def _make_legacy_row(self, img_id: str, decision: str = "relevant") -> dict:
        return {
            "img_id": img_id,
            "filing_key": "0001234567-23-000001",
            "filename": "chart.png",
            "decision": decision,
            "chart_type": "cohort_table",
            "rejection_reason": None,
            "reviewer_notes": "looks good",
            "storage_key": f"pipeline/123/{img_id}/chart.png",
            "accession_number": "0001234567-23-000001",
            "cik": "123456",
            "company_name": "Acme Corp",
            "relevance_score": 0.9,
        }

    def _make_confirmation_row(self, img_id: str, decision: str = "relevant") -> dict:
        return {
            "img_id": img_id,
            "filing_key": "0001234567-23-000001",
            "filename": "chart.png",
            "decision": decision,
            "chart_type": None,  # not captured in v2_image_metric_confirmations
            "rejection_reason": None,
            "reviewer_notes": None,
            "storage_key": f"pipeline/123/{img_id}/chart.png",
            "accession_number": "0001234567-23-000001",
            "cik": "123456",
            "company_name": "Acme Corp",
            "relevance_score": 0.7,
        }

    def _apply_dedup(
        self,
        legacy_rows: list[dict],
        confirmation_rows: list[dict],
    ) -> list[dict]:
        """Replicate the dedup logic from benchmark_vision.py --build-corpus."""
        legacy_img_ids = {str(r["img_id"]) for r in legacy_rows}
        return list(legacy_rows) + [
            r for r in confirmation_rows if str(r["img_id"]) not in legacy_img_ids
        ]

    def test_legacy_only_row_passes_through(self) -> None:
        """A legacy-only img_id appears in the output unchanged."""
        legacy = [self._make_legacy_row("aaa")]
        result = self._apply_dedup(legacy, [])
        assert len(result) == 1
        assert result[0]["img_id"] == "aaa"
        assert result[0]["chart_type"] == "cohort_table"
        assert result[0]["decision"] == "relevant"

    def test_confirmation_only_row_passes_through(self) -> None:
        """A confirmation-only img_id appears in the output with chart_type=None."""
        conf = [self._make_confirmation_row("bbb")]
        result = self._apply_dedup([], conf)
        assert len(result) == 1
        assert result[0]["img_id"] == "bbb"
        assert result[0]["chart_type"] is None

    def test_legacy_wins_on_duplicate_img_id(self) -> None:
        """When the same img_id appears in both surfaces, the legacy row wins."""
        shared_id = "ccc"
        legacy = [self._make_legacy_row(shared_id, decision="relevant")]
        conf = [self._make_confirmation_row(shared_id, decision="not_relevant")]
        result = self._apply_dedup(legacy, conf)
        # Only one row — legacy wins.
        assert len(result) == 1
        assert result[0]["decision"] == "relevant"
        assert result[0]["chart_type"] == "cohort_table"

    def test_all_three_scenarios_combined(self) -> None:
        """One legacy-only, one confirmation-only, one overlap — correct output."""
        legacy = [
            self._make_legacy_row("legacy-only"),
            self._make_legacy_row("overlap-id", decision="relevant"),
        ]
        conf = [
            self._make_confirmation_row("conf-only"),
            self._make_confirmation_row("overlap-id", decision="not_relevant"),
        ]
        result = self._apply_dedup(legacy, conf)
        assert len(result) == 3  # legacy-only + overlap(legacy) + conf-only
        img_ids = {r["img_id"] for r in result}
        assert "legacy-only" in img_ids
        assert "conf-only" in img_ids
        assert "overlap-id" in img_ids
        overlap = next(r for r in result if r["img_id"] == "overlap-id")
        assert overlap["decision"] == "relevant"
        assert overlap["chart_type"] == "cohort_table"

    def test_confirmation_row_chart_type_is_none(self) -> None:
        """Confirmation-derived rows always have chart_type=None (no column in schema)."""
        conf = [self._make_confirmation_row("ddd", decision="not_relevant")]
        result = self._apply_dedup([], conf)
        assert result[0]["chart_type"] is None

    def test_corpus_query_constants_exist(self) -> None:
        """Both query constants must exist and reference their respective tables."""
        assert "_CORPUS_QUERY_LEGACY" in dir(bv)
        assert "_CORPUS_QUERY_CONFIRMATIONS" in dir(bv)
        assert "v2_image_review_decisions" in bv._CORPUS_QUERY_LEGACY
        assert "v2_image_metric_confirmations" in bv._CORPUS_QUERY_CONFIRMATIONS
        # Old monolithic _CORPUS_QUERY must no longer exist.
        assert not hasattr(bv, "_CORPUS_QUERY"), (
            "_CORPUS_QUERY was removed; use _CORPUS_QUERY_LEGACY and _CORPUS_QUERY_CONFIRMATIONS"
        )
