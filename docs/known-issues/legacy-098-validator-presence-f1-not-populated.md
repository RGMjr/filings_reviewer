---
autonomy: review
discovered: '2026-04-24'
estimated: S
id: 98
note: 'PR #150 added the presence P/R/F1 infrastructure to the validator + baseline,
  but presence_f1 is emitted as None because v2_context.images[*].detected_metrics
  is not populated during the validator''s in-memory pipeline run. Baseline refresh
  in PR 4b (2026-04-24) has presence_f1=null as a result.'
severity: low
slug: validator-presence-f1-not-populated
source: legacy
status: open
title: Validator presence_f1 Stays Null — detected_metrics Not Populated in-Memory
touches:
  - src/gold_standard/v2_validator.py
  - src/extraction_v2/stages/chart_fact_bridge.py
updated: '2026-04-24'
---

### Problem

The chart-presence pivot landed presence P/R/F1 infrastructure in PR #150:

- `FilingResult.presence_tp / presence_fp / presence_fn` fields (`src/gold_standard/v2_validator.py`).
- `BaselineMetrics.presence_f1` field (`src/gold_standard/baseline.py`).
- `to_dict()` emits `presence_f1` only when `has_presence = (total_presence_tp + total_presence_fp + total_presence_fn) > 0` (`src/gold_standard/v2_validator.py:374`).

After the PR 4b baseline refresh on 2026-04-24, `v2_baseline.json` has `presence_f1` **absent at all scopes** (overall and per-company). The pre-PR-4a baseline (2026-04-23) also lacked it. That means the validator has been silently computing zero presence TP/FP/FN for every run since PR #150 landed.

Root cause (likely): the validator calls `V2Pipeline(...).process(..., document_date=...)` with `filing_id=0` (no persistence). The pipeline's chart bridge stage writes `image.detected_metrics` in-memory. But either:

1. The chart bridge stage isn't firing because chart images aren't reaching it — e.g., vision calls skipped under test harness, `chart_data` never populated → classifier runs on empty input → no presence emitted.
2. The validator accesses `v2_context.images` via a getter that doesn't surface the in-memory `detected_metrics` populated by the bridge.
3. Something else in the `filing_id=0` mode skips the full image pipeline.

Confirmed via grep: `_chart_presence_set_from_context` (`v2_validator.py` around the presence block) reads `v2_context.images[*].detected_metrics`. The validator does walk through that code path. But `presence_tp/fp/fn` stay 0.

### Impact

- Presence-F1 is unmeasurable via the GS pipeline right now. Chart-native metric improvements can't be quantified — the baseline has no floor to regress against.
- The 30% cross-source confirmation gate (`_derive_chart_native_metrics`) still works (it's CSV-driven, not pipeline-driven), so metric-aware classification isn't affected.
- Not a correctness issue; it's a measurement gap.

### Next Steps

1. Instrument `_chart_presence_set_from_context` to log `len(v2_context.images)` and how many have non-empty `detected_metrics`. Run against one filing with a known chart (e.g., Robinhood S-1 has chart images).
2. If images reach the validator but `detected_metrics` is empty → inspect `ChartFactBridgeStage.process()` — did vision OCR fire? Did `classify_all` return anything? Check `chart_presence_min_score` threshold.
3. If the images list is empty → the validator's pipeline run is skipping image-processing stages. Check `PipelineConfig` defaults used by the validator vs. the prod config.
4. Fix whichever gap is real, re-run the baseline refresh, confirm `presence_f1` field appears.

### Cross-References

- Parent rollout: legacy-096.
- Introducing PR: #150.
- Baseline refresh PR (where this was surfaced): PR 4b.
