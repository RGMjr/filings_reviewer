---
autonomy: review
discovered: '2026-04-22'
estimated: M
id: 87
note: Root cause likely in PR #110 (full-page OCR + Tier-1 pre-scan); needs git bisect between 8840912 and current main. Renumbered from #85 → #87 during b4 rebase (PR #130 took #85, PR #135 took #86).
severity: medium
slug: text-recall-regression-farfetch-robinhood
source: legacy
status: open
title: Text Recall Regression on Farfetch + Robinhood Between 04-19 and 04-22 Baselines
touches:
  - src/extraction_v2/pipeline.py
  - src/extraction_v2/stages/image_triage.py
  - src/extraction_v2/stages/ocr_extraction.py
  - data/gold_standard/v2_baseline.json
updated: '2026-04-22'
---

### Problem

Between the 04-19 gold-standard baseline (`8840912`) and current `main` (post-B3
merge), text-only gold-standard recall regressed meaningfully on two companies.
The regression was discovered when Wave B4 (two-stage vision routing) hit the
pre-commit `extraction-guard`. B4's code is **not** the cause — the validator
runs without `OPENAI_API_KEY`, so Stages 4–5 (image/chart) are disabled and B4
code never executes during validation.

### Measured impact

Validator run on plain `main` (no B4), `--fail-on-regression`:

| Metric | 04-19 baseline | Current | Delta |
|---|---|---|---|
| Overall precision | 0.664 | 0.668 | +0.004 |
| Overall recall | 0.498 | 0.459 | **−0.039** |
| Overall F1 | 0.569 | 0.544 | −0.025 |
| Farfetch recall | 0.867 | 0.533 | **−0.333** |
| Farfetch F1 | 0.765 | 0.561 | −0.204 |
| Robinhood | — regressed recall + f1 — | | |

Farfetch lost **10 specific facts** (TP 26 → 16). The other 13 companies in the
gold standard appear unchanged.

### Preserved baseline

The pre-regression 04-19 baseline is preserved at
`data/gold_standard/v2_baseline_pre_regression_2026-04-22.json` for direct
comparison once the root cause is identified. Do NOT delete this file without
resolving this issue first.

### Suspect commits

Commits between `8840912` (04-19 baseline) and HEAD that touched
`src/extraction_v2/` or `config/metric_keywords.yaml`:

| Commit | PR | Touches | Likelihood |
|---|---|---|---|
| `b517f75` | #110 | `pipeline.py`, `persistence.py`, `image_triage.py`, `ocr_extraction.py` (+440 / −7) | **Primary suspect** — only commit that modified `pipeline.py` and `persistence.py` |
| `a9da728` | #114 | `pipeline.py` (+26) — env var wiring for full-page OCR | Secondary |
| `e20fb04` | #121 | `image_triage.py`, `ocr_extraction.py` — observability counters | Unlikely (counters only) |
| `7b02584` | #131 | `ocr_extraction.py` — chart dollar budget | Unlikely (chart path only) |
| `fe4e544` | #132 | `models.py`, `image_triage.py`, `image_features.py` — ML triage gate | Unlikely (gate default OFF) |

### Why #110 is the primary suspect

PR #110 introduced full-page OCR (Path A) and Tier-1 keyword pre-scan (Path B).
Both are gated on `enable_full_page_ocr` and `enable_image_keyword_prescan`
`PipelineConfig` flags that default `False`. In theory, text-only extraction
should be unaffected. In practice, #110 touched:

1. `src/extraction_v2/pipeline.py` — added `PipelineContext.full_page_scan_mode`
   field plus two `PipelineConfig` flags.
2. `src/extraction_v2/persistence.py` — extended the `v2_segments` INSERT with
   `source_type` + `source_img_id` columns (validator doesn't persist; not a
   factor here).
3. `src/extraction_v2/stages/image_triage.py` — added full-page-scan detector
   (`_detect_full_page_scan_filing`) that runs unconditionally, classifying
   some images as `FULL_PAGE_SCAN` even in flag-off mode.
4. `src/extraction_v2/stages/ocr_extraction.py` — added `_prescan_ambiguous_images`
   and `process_full_page_scan` methods. The pre-scan runs at the top of
   `OCRExtractionStage.process` on images with `classification == UNKNOWN` and
   `relevance_score ∈ [0.2, 0.3)`.

**Hypothesis:** the full-page-scan detector changed classification decisions
for some Farfetch images, which in turn altered what text candidates
`candidate_generation._scan_chart` extracts from image metadata (title / axis /
annotations). Even without vision calls, the triage stage's classification
output feeds downstream text scanning.

### Investigation plan (for follow-up session)

1. `git checkout b517f75^` (commit before #110). Run
   `python3 -m src.gold_standard.v2_validator --companies "Farfetch Limited"`.
   If Farfetch recall is back to 0.867, #110 is confirmed.
2. Diff `b517f75` for `image_triage.py` changes that run unconditionally
   (outside the `enable_full_page_ocr` guard). Look at
   `_detect_full_page_scan_filing` and whether it sets
   `classification = FULL_PAGE_SCAN` in flag-off mode.
3. Identify the 10 missing Farfetch facts — run with `--fn-diagnostics`
   on both baseline and current main, diff the FN lists.
4. Proposed fix: make `_detect_full_page_scan_filing` a no-op when
   `config.enable_full_page_ocr is False`, OR preserve the original
   classification for images in text-only filings.

### Workaround applied

Baseline refreshed to current (regressed) numbers with this fragment referenced
in the description. Accepts 10-fact Farfetch loss as a known issue pending
proper fix. Wave B4 (two-stage routing) and future extraction-touching PRs
are unblocked.

### Acceptance criteria for resolution

- [ ] Farfetch recall restored to ≥ 0.85 on the 04-19 gold standard
- [ ] Robinhood recall non-regressed vs. 04-19
- [ ] Fix PR restores baseline and deletes
      `data/gold_standard/v2_baseline_pre_regression_2026-04-22.json`
- [ ] Post-mortem comment in this fragment naming the actual root cause
