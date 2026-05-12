# Analysis & Evaluation Reports

This directory contains active validation reports, evaluation results, and analysis documentation. Completed and superseded documents are in `docs/archive/analysis/`.

---

## Current Documents

### V1_RETIREMENT_CODE_SCAN_2026-04-18.md

**Status**: Active reference
**Date**: 2026-04-18

Catalog of dead V1 references and active V1 code still requiring migration during V1 retirement. Covers `src/`, `scripts/`, `tests/`, and non-archive `docs/`.

---

### gs-baseline-drift-investigation-2026-04-25.md

**Status**: Active — tied to known-issue `legacy-108`
**Date**: 2026-04-25

Root-cause analysis of the `has_regression=True` false positive when running `--companies "Farfetch Limited" --fail-on-regression`. Identifies a comparator design flaw in `compare_to_baseline` (subset vs. full-corpus comparison). No baseline update needed; fix tracked in known-issue #108.

---

### chart-type-decision.md

**Status**: Pending approval
**Date**: 2026-04-25

Product decision memo on how to handle the missing `chart_type` signal in `v2_image_metric_confirmations` (surfaced by PR #198 / gh-196). Recommends Option A (extend the confirmations table) over reworking `benchmark_vision.py`.

---

### gh-405-chart-classifier-overflag-audit.md

**Status**: Complete — recommends closing gh-405
**Date**: 2026-05-01

Audit of `_is_chart()` over-flagging behavior triggered by the `is_chart_classification: -2.178` coefficient in the retrained relevance model. Reproduces the coefficient (1,499 samples, AUC 0.829), decomposes chart-classification by gate origin, and concludes the relevance model already absorbs the over-flag signal correctly — no rule change recommended.

---

### metric-value-evaluation.md

**Status**: Reference
**Date**: 2026-04-15

Evaluation of all 28 active metrics in `config/metric_keywords.yaml` against the criterion of genuine customer value disclosure vs. noise. Includes historical note on V1/V2 coexistence context at the time of writing.

---

### vision-bakeoff-2026-04-23.md

**Status**: Complete — results reference
**Date**: 2026-04-23

Five vision provider configurations benchmarked for chart detection (F1) and cost/latency via `scripts/benchmark_vision.py --bakeoff` against a 7-image corpus. All providers hit F1=1.0 on detection; `gemini-2.5-flash-lite` was cheapest/fastest.

---

### vision-bakeoff-chart-read-2026-04-23.md

**Status**: Complete — results reference
**Date**: 2026-04-23

Companion to the detection bakeoff; benchmarks chart-READ mode (`analyze_image_targeted`) across 6 provider configurations, scoring extracted values against `extracted_values.csv`. Includes `two-stage` (B4 routing) evaluation.

---

### vision-bakeoff-metric-classify-2026-04-23.md

**Status**: Complete — results reference
**Date**: 2026-04-23

Third leg of the 2026-04-23 vision sweep; benchmarks metric-CLASSIFY mode across 5 provider configurations — given a chart image, which Tier-1/Tier-2 metric does it disclose?

---

### llm-presence-classifier-phase2-eval-results-20260511.md

**Status**: Complete — gate decision: NO-GO
**Date**: 2026-05-11

First live Phase-2 quantitative gate run (`scripts/run_phase2_quantitative_eval.py`, run_id `20260511T1416live`). 55 filings (8 gold + 47 reviewed), $13.75 spend, 0 errors of 550 calls. Headline: classifier recall == keyword recall to 3 decimals on all 10 scoreable Tier-1 metrics; C3 (+5pt improvement gate) structurally unreachable from the 98.8% keyword baseline. 5 Tier-1 metrics skipped for insufficient coverage. Surfaced gh-602 (dedup-by-URL), gh-612 (section_classification variant), gh-613 (cache counter bug).

---

## Archive

Completed tasks, superseded reports, and research spikes are in `docs/archive/analysis/`. This includes all HRV-3 through HRV-6 validation docs, IMG-1-x completion summaries, GR-series validation reports, VIS-series chart extraction research, the beyond-SEC spike, and the 2025-12-26 comprehensive evaluation plan.

---

**Last Updated**: 2026-05-12
