# Gold Standard Validator Memory

## Key Paths
- Transcript benchmark: `scripts/validate_transcript_extraction.py --baseline`
- Presentation benchmark: `scripts/validate_presentation_extraction.py --verbose`
- SEC gold standard: `pytest -m gold_standard --gold-standard-mode=fresh -v` (runs from worktree dir)
- SEC validate_against_gold_standard.py requires live DB — produces 0 candidates without it; use pytest instead
- Transcript baseline JSON: `data/spike_samples/transcript_baseline.json`
- Transcript HTML files: `data/spike_samples/transcripts_html/*.html`
- Transcript annotations: `data/transcript_gold_standard/transcript_gold_standard.csv`

## Baselines (as of 2026-03-02)
- Transcript: R=75.8%, P=74.2%, F1=75.0% (91 annotations, 20 files)
- Presentation: R=100%, P=36.8%, F1=53.8% (7 annotations, 5 files) — initial baseline 2026-03-11
- SEC: pytest 3 passed (DB-requiring tests skipped)

## Known Regression Pattern: _DELTA_BY_MORE_RE Over-broad Match
- Rule in `false_positive_filter.py` catches "by more than" in pre-30-char window before value
- FP regex block: "Facebook is used by more than 3 billion" — "used by more than" is NOT delta
- Fix: require "by" to be preceded by directional/motion verb, not passive ("used by", "adopted by")
- Affected filing: META_2025-01-29 `cm_monthly_active_users: 3000000000`

## Known Flaky Transcript Files
- TMUS_2025-04-24: varies between 4 and 5 TPs depending on run (dedup ordering)
- META_2025-04-30: can miss 1 extra MAU value per run (non-deterministic cross-metric dedup)
- Tolerance: 1pp per metric before flagging regression

## Presentation Notes
- SNAP filings (Q3 and Q4 2025): image-based investor letter — poor precision (29%), many spurious text FPs
- ADBE presentation: zero extraction (only 12 paragraph segments, no metrics matched)
- CRM and META presentations: 100% R/P/F1 on current gold standard

## SEC Gold Standard
- `validate_against_gold_standard.py --all --mode fresh --baseline` requires DB; always shows 0/0 without it
- Use `pytest -m gold_standard --gold-standard-mode=fresh` for authoritative SEC check
- Coverage check FAILS (20-21%) — this is expected; --cov is included but most code isn't exercised by gold_standard tests

## V2 FN Root Cause Distribution (2026-04-04 baseline)
- V2 overall: P=66.9%, R=49.7%, F1=57.0% (TP=160, FP=79, FN=162; note: ~3 FNs listed as 159 in summary)
- FN API: `V2GoldStandardValidator(fn_diagnostics=True)` then `V2GoldStandardValidator.print_fn_diagnostics(results)`
- wrong_value: 71 FNs (45%) — largest category; value extracted but wrong magnitude/scale
  - Samsara ARR: closest=1.0 vs expected ~100-500 — scale stripping artifact
  - Torrid active customers: 1202 extracted vs 3000-3400 expected — wrong row selected in table
  - Robinhood customers: 30 vs 5-22M expected — scale unit dropped
  - GitLab large customers: 31 extracted vs 11-2745 expected — wrong candidate row
- low_confidence: 23 FNs (14%) — value extracted correctly but confidence < 0.5 threshold
  - Torrid LTV/CAC/CAC metrics: conf=0.33; Kingsoft customers: conf=0.46
  - Fix path: lower threshold for specific metric types OR improve scorer for these patterns
- no_candidate: 23 FNs (14%) — metric_id not even matched in filing
  - Kingsoft cm_revenue_per_customer (5 FNs) — metric not in keyword config
  - Robinhood cm_balance_by_cohort (9 FNs) — metric not in keyword config
  - Samsara/Tenable cm_revenue_concentration — keyword not triggering
- no_value_binding: 16 FNs (10%) — candidate found but value extractor returned nothing
  - Farfetch cm_gross_margin_by_cohort (6 FNs) — table extraction issue
  - Maplebear cm_revenue_by_cohort (8-9 FNs) — "x" multiplier values (1.00x, 1.73x) not parsed
- wrong_period: 16 FNs (10%) — value/metric match but period attribution wrong
  - Robinhood MAU (4 FNs), GitLab/Kingsoft NRR, Tenable new customers
- fp_filtered: 10 FNs (6%) — correct value removed by FP filter (false FP block)
  - Flywire NRR (4 FNs), Tenable large customers (2 FNs), Maplebear transactions (1 FN)
